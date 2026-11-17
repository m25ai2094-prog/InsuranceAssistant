"""Loopback web UI, session management, and Rasa custom action protocol."""

import hmac
import json
import os
import re
import secrets
from collections import OrderedDict, deque
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from threading import Lock
from time import monotonic, perf_counter
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener
from uuid import UUID

from flask import Flask, abort, jsonify, make_response, request
from werkzeug.exceptions import HTTPException

from .repository import DEMO_CLAIM, POLICIES, Repository
from .workflow import Conversation, OTP_TTL, PRIVATE_STEPS, Reply, Workflow, normalize
from .light_nlu import classify_message


COOKIE_NAME = "insurance_demo_session"
SESSION_TTL = 1800
SESSION_LIMIT = 256
CANCEL = {"cancel", "cancel this request", "cancel the claim", "start over", "menu", "restart"}
REDACTIONS = (
    (r"\b(?:POL|CLM|SUP)-[A-Z0-9-]+\b", "[reference]"),
    (r"\b[\w.+-]+@[\w.-]+\.\w+\b", "[email]"),
    (r"\b\d{4}-\d{2}-\d{2}\b", "[date]"),
    (r"(?<!\w)\+?\d(?:[ ()-]*\d){5,}(?!\w)", "[number]"),
)


def redact(text: str) -> str:
    for pattern, replacement in REDACTIONS:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def rasa_request(port: int, path: str, *, body: dict | None = None, timeout: float = 2):
    data = json.dumps(body).encode() if body is not None else None
    request_to_rasa = Request(
        f"http://127.0.0.1:{port}{path}", data=data,
        headers={"Content-Type": "application/json"} if data else {},
    )
    with build_opener(ProxyHandler({})).open(request_to_rasa, timeout=timeout) as response:
        return response.read()


@dataclass
class Session:
    state: Conversation
    rasa_sender: str = field(default_factory=lambda: secrets.token_urlsafe(24))
    seen: float = field(default_factory=monotonic)
    guard: Lock = field(default_factory=Lock)
    trace: deque = field(default_factory=lambda: deque(maxlen=6))
    cache: OrderedDict = field(default_factory=OrderedDict)
    last_model: dict | None = None
    last_reply: dict | None = None
    closed: bool = False


@dataclass
class PendingTurn:
    session: Session
    text: str
    source: str
    echo: str
    started: float = field(default_factory=perf_counter)
    guard: Lock = field(default_factory=Lock)
    result: dict | None = None
    closed: bool = False


class RasaBridge:
    def __init__(self, rasa_port: int, action_token: str, workflow: Workflow):
        self.rasa_port = rasa_port
        self.action_token = action_token
        self.workflow = workflow
        self.pending: dict[str, PendingTurn] = {}
        self.pending_guard = Lock()

    def send(self, session: Session, text: str) -> dict | None:
        state = session.state
        if normalize(text) in CANCEL:
            model_text, source = "/cancel", "workflow"
        elif state.step != "menu":
            model_text, source = "/provide_input", "workflow"
        else:
            model_text, source = redact(text), "diet"

        turn_id = secrets.token_urlsafe(24)
        echo = PRIVATE_STEPS.get(state.step, redact(text))
        if model_text == "/cancel":
            echo = "Cancel"
        if state.step == "otp" and normalize(text) == "resend code":
            echo = "Resend code"
        turn = PendingTurn(session, text, source, echo)
        with self.pending_guard:
            self.pending[turn_id] = turn

        try:
            rasa_request(
                self.rasa_port, "/webhooks/rest/webhook", timeout=20,
                body={
                    "sender": session.rasa_sender, "message": model_text,
                    "metadata": {"turn_id": turn_id},
                },
            )
        except (OSError, URLError):
            # A committed action may have completed before the HTTP response was lost.
            pass
        finally:
            with turn.guard:
                turn.closed = True
                result = turn.result
            with self.pending_guard:
                self.pending.pop(turn_id, None)
        return result

    def execute(self, payload: dict) -> dict:
        if not isinstance(payload, dict) or payload.get("next_action") != "action_insurance_workflow":
            abort(400, "Unknown custom action.")
        tracker = payload.get("tracker") or {}
        message = tracker.get("latest_message") or {}
        turn_id = (message.get("metadata") or {}).get("turn_id")
        if not isinstance(turn_id, str):
            abort(403, "Missing turn capability.")
        with self.pending_guard:
            turn = self.pending.get(turn_id)
        if turn is None or not hmac.compare_digest(
            str(payload.get("sender_id", "")), turn.session.rasa_sender,
        ):
            abort(403, "Invalid turn capability.")

        with turn.guard:
            if turn.closed:
                abort(403, "Turn has expired.")
            if turn.result is None:
                model_intent = message.get("intent") or {}
                intent = str(model_intent.get("name") or "nlu_fallback")
                if turn.source == "diet" and intent == "provide_input":
                    intent = "nlu_fallback"
                confidence = model_intent.get("confidence")
                if turn.source != "diet" or intent == "nlu_fallback":
                    confidence = None
                flow_before = turn.session.state.flow
                reply = self.workflow.handle(
                    turn.session.state, intent, turn.text, message.get("entities") or [],
                )
                state = turn.session.state
                trace = {
                    "intent": intent, "confidence": confidence, "source": turn.source,
                    "event": reply.event, "flow": state.flow if state.flow != "menu" else flow_before,
                    "server_ms": round((perf_counter() - turn.started) * 1000, 2),
                }
                if turn.source == "diet":
                    turn.session.last_model = trace
                turn.session.trace.appendleft(trace)
                turn.result = present(turn.session, reply, turn.echo)

        # Only a controlled event code is returned to the Rasa tracker.
        return {"events": [], "responses": [{"custom": {"event": turn.result["event"]}}]}


class LightweightBridge:
    """Low-memory intent router for free cloud hosting; workflow logic is unchanged."""

    def __init__(self, workflow: Workflow):
        self.workflow = workflow

    def send(self, session: Session, text: str) -> dict:
        started = perf_counter()
        state = session.state
        normalized = normalize(text)
        if normalized in CANCEL:
            intent, confidence, entities, source = "cancel", 1.0, [], "workflow"
            echo = "Cancel"
        elif state.step != "menu":
            intent, confidence, entities, source = "provide_input", None, [], "workflow"
            echo = PRIVATE_STEPS.get(state.step, redact(text))
            if state.step == "otp" and normalized == "resend code":
                echo = "Resend code"
        else:
            intent, confidence, entities = classify_message(text)
            source = "lightweight_rules"
            echo = redact(text)

        flow_before = state.flow
        reply = self.workflow.handle(state, intent, text, entities)
        trace = {
            "intent": intent, "confidence": confidence, "source": source,
            "event": reply.event,
            "flow": state.flow if state.flow != "menu" else flow_before,
            "server_ms": round((perf_counter() - started) * 1000, 2),
        }
        if source == "lightweight_rules":
            session.last_model = trace
        session.trace.appendleft(trace)
        return present(session, reply, echo)


def present(session: Session, reply: Reply, echo: str = "") -> dict:
    return {
        **asdict(reply),
        "echo": echo,
        "step": session.state.step,
        "flow": session.state.flow,
        "trace": list(session.trace),
        "last_model": session.last_model,
    }


def create_app(database, rasa_port: int | None = None, action_token: str | None = None, *, lightweight: bool = False) -> Flask:
    app = Flask(__name__, static_url_path="/assets", static_folder="static")
    app.config.update(MAX_CONTENT_LENGTH=8192, TRUSTED_HOSTS=None)
    workflow = Workflow(Repository(database))
    bridge = LightweightBridge(workflow) if lightweight else RasaBridge(rasa_port, action_token, workflow)
    sessions: dict[str, Session] = {}
    sessions_guard = Lock()

    def get_session() -> Session:
        key = request.cookies.get(COOKIE_NAME, "")
        with sessions_guard:
            current = sessions.get(key)
        if current is None or current.closed or monotonic() - current.seen >= SESSION_TTL:
            abort(401, "This demo session expired. Refresh the page to start again.")
        return current

    def new_session() -> Session:
        now = monotonic()
        with sessions_guard:
            for key, current in list(sessions.items()):
                if now - current.seen >= SESSION_TTL and not current.guard.locked():
                    sessions.pop(key)
            if len(sessions) >= SESSION_LIMIT:
                abort(503, "The local session limit was reached. Try again later.")
            key = secrets.token_urlsafe(32)
            current = Session(Conversation(key))
            sessions[key] = current
        return current

    def demo_records():
        return [
            {
                "policy": row[0], "mobile": row[1], "category": row[2].title(),
                "claim": DEMO_CLAIM if index == 0 else None,
                "incident_date": (
                    min(date.today() - timedelta(days=2), date.fromisoformat(row[6]))
                ).isoformat(),
            }
            for index, row in enumerate(POLICIES) if row[-1] == "Active"
        ]

    def session_response(session: Session):
        expired = workflow.expire_verification(session.state)
        if expired:
            session.last_reply = None
            reply = present(session, expired)
        else:
            reply = session.last_reply if session.state.step != "menu" else None
        response = make_response(jsonify(
            message=reply or present(session, workflow.welcome()), demo_records=demo_records(),
        ))
        response.set_cookie(COOKIE_NAME, session.state.key, httponly=True, samesite="Strict", secure=bool(os.environ.get("RENDER")))
        return response

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self'; script-src 'self'; "
            "object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
        )
        if not request.path.startswith("/assets/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error=error.description), error.code

    @app.get("/")
    def index():
        return app.send_static_file("index.html")

    @app.get("/api/health")
    def health():
        if lightweight:
            return jsonify(status="ready", model="Lightweight rule-based intent router", workflow="same validated Python workflows")
        try:
            rasa_request(rasa_port, "/")
        except (OSError, URLError):
            return jsonify(status="unavailable"), 503
        return jsonify(status="ready", model="Rasa Open Source 3.6.21 · DIET + RulePolicy")

    @app.get("/api/session")
    def session_start():
        try:
            session = get_session()
        except HTTPException as error:
            if error.code != 401:
                raise
            session = new_session()
        with session.guard:
            if session.closed:
                abort(401, "This session was cleared. Refresh the page.")
            session.seen = monotonic()
            return session_response(session)

    @app.post("/api/reset")
    def session_reset():
        session = get_session()
        with session.guard:
            session.closed = True
            session.state.clear()
            with sessions_guard:
                sessions.pop(session.state.key, None)
        return session_response(new_session())

    @app.get("/api/demo-inbox")
    def demo_inbox():
        session = get_session()
        with session.guard:
            if session.closed:
                abort(401, "This session was cleared. Refresh the page.")
            challenge = session.state.otp
            if challenge is None or challenge.demo_code is None:
                return jsonify(code=None)
            remaining = int(OTP_TTL - (monotonic() - challenge.issued))
            if remaining <= 0:
                return jsonify(code=None)
            return jsonify(code=challenge.demo_code, expires_in=remaining)

    @app.post("/api/chat")
    def chat():
        session = get_session()
        body = request.get_json()
        if not isinstance(body, dict) or not isinstance(body.get("text"), str):
            abort(400, "Send a message as text.")
        text = body["text"].strip()
        if not text or len(text) > 400 or text.startswith("/"):
            abort(400, "Enter a message of 1 to 400 characters. Use the menu for commands.")
        try:
            request_id = UUID(str(body.get("request_id"))).hex
        except (ValueError, TypeError):
            abort(400, "Send a valid request ID.")
        with session.guard:
            if session.closed:
                abort(401, "This session was cleared. Refresh the page.")
            session.seen = monotonic()
            if request_id in session.cache:
                return jsonify(session.cache[request_id])
            response = bridge.send(session, text)
            if response is None:
                abort(503, "The local model or action service is unavailable. Retry the same message.")
            session.cache[request_id] = response
            if len(session.cache) > 32:
                session.cache.popitem(last=False)
            session.last_reply = response
            return jsonify(response)

    @app.post("/internal/rasa/action")
    def rasa_action():
        if lightweight:
            abort(404)
        supplied = request.headers.get("Authorization", "")
        if not hmac.compare_digest(supplied, "Bearer " + bridge.action_token):
            abort(403, "This endpoint is for the local Rasa service.")
        request.max_content_length = 65_536
        return jsonify(bridge.execute(request.get_json()))

    return app
