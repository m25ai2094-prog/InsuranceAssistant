"""Deterministic insurance workflows called by the Rasa custom action."""

import hmac
import json
import re
import secrets
from collections import deque
from dataclasses import dataclass, field
from datetime import date
from time import monotonic

from .catalog import PRODUCTS, category_from_text, eligible_plans, required_documents
from .repository import Repository


MENU = ("Recommend a policy", "View my policy", "Register a claim",
        "Track a claim", "Claim document checklist", "Check premium due", "Talk to a person")
PRODUCT_CHOICES = tuple(product.label for product in PRODUCTS.values())
PRIVATE_STEPS = {
    "policy_number": "[Policy number entered]",
    "mobile": "[Mobile entered]",
    "otp": "[Verification code entered]",
    "claim_reference": "[Claim reference entered]",
    "description": "[Incident description entered]",
    "provider": "[Facility name entered]",
}
PROTECTED_FLOWS = {"policy_details", "premium_due", "claim_intimation", "claim_status"}
VERIFIED_STEPS = {
    "claim_type", "incident_date", "description", "provider", "documents",
    "confirmation", "claim_reference",
}
OTP_TTL = 180
VERIFY_TTL = 600


@dataclass
class Challenge:
    digest: bytes
    demo_code: str | None
    issued: float
    attempts: int = 3


@dataclass
class Conversation:
    key: str
    flow: str = "menu"
    step: str = "menu"
    draft_id: str = ""
    draft: dict = field(default_factory=dict)
    otp: Challenge | None = None
    verified_policy: str | None = None
    verified_until: float = 0.0
    otp_issues: deque = field(default_factory=deque)
    fallbacks: int = 0

    def open(self, flow: str, step: str):
        self.clear()
        self.flow, self.step = flow, step
        self.draft_id = secrets.token_hex(16)

    def clear(self):
        self.flow = self.step = "menu"
        self.draft_id = ""
        self.draft.clear()
        self.otp = None
        self.verified_policy = None
        self.verified_until = 0.0
        self.fallbacks = 0


@dataclass
class Reply:
    text: str
    event: str
    options: tuple[str, ...] = ()
    items: tuple[str, ...] = ()
    card: dict | None = None


def menu_reply(text: str, event: str) -> Reply:
    return Reply(text, event, MENU)


def normalize(text: str) -> str:
    return " ".join(text.casefold().split()).strip(" .!?,")


def mask_policy(number: str) -> str:
    return f"Policy ending in {number[-4:]}"


def format_inr(amount: int) -> str:
    digits = str(amount)
    prefix, tail = digits[:-3], digits[-3:]
    groups = []
    while prefix:
        groups.insert(0, prefix[-2:])
        prefix = prefix[:-2]
    return "₹" + ",".join([*groups, tail])


def card(title: str, rows: list[tuple[str, str]], *, tone: str = "neutral") -> dict:
    return {"title": title, "rows": rows, "tone": tone}


class Workflow:
    def __init__(self, repository: Repository):
        self.repository = repository
        self.otp_key = secrets.token_bytes(32)

    def welcome(self) -> Reply:
        return menu_reply(
            "Hello. I can compare sample plans, look up a policy, help register a claim, "
            "or track one you have already filed. What would you like to do?",
            "session_started",
        )

    def handle(self, state: Conversation, intent: str, text: str, entities: list[dict]) -> Reply:
        if intent == "cancel":
            state.clear()
            return menu_reply("I cleared the current request. What would you like to do next?",
                              "workflow_cancelled")
        if state.step != "menu" and intent == "provide_input":
            return self.expire_verification(state) or self.collect(state, text)

        if intent in PROTECTED_FLOWS:
            state.open(intent, "policy_number")
            self.repository.audit(state.key, intent, "protected_flow_started")
            return Reply("Enter the demo policy number to begin verification.", "ask_policy")
        if intent in {"insurance_advisory", "document_checklist"}:
            state.open(intent, "category")
            categories = {
                category_from_text(str(entity.get("value", ""))) for entity in entities
                if entity.get("entity") == "product_category"
            } - {None}
            if len(categories) == 1:
                return self.select_category(state, categories.pop())
            return Reply("Which type of insurance do you need?", "ask_category", PRODUCT_CHOICES)
        if intent == "human_handoff":
            state.open(intent, "support_topic")
            return Reply("What should the support team help you with?", "ask_support_topic",
                         ("Policy", "Claim", "Other"))
        if intent == "greet":
            state.fallbacks = 0
            return self.welcome()

        state.fallbacks += 1
        if state.fallbacks > 1:
            return menu_reply("I can help with insurance policies and claims. "
                              "You can also choose Talk to a person.", "nlu_fallback")
        return menu_reply("I couldn't match that to an insurance request. "
                          "Try a shorter request or choose an option.", "nlu_fallback")

    def select_category(self, state: Conversation, category: str) -> Reply:
        state.draft["category"] = category
        if state.flow == "document_checklist":
            state.step = "checklist_type"
            return Reply("Which claim type do you need the checklist for?", "ask_checklist_type",
                         PRODUCTS[category].claims)
        state.step = "age"
        return Reply("Enter an age from 18 to 90 for the sample plan comparison.", "ask_age")

    def collect(self, state: Conversation, text: str) -> Reply:
        """Resolve the active step using validated input instead of model output."""
        step = state.step
        value = normalize(text)
        if step == "category":
            category = category_from_text(value)
            if category is not None:
                return self.select_category(state, category)
            return Reply("Choose Health, Motor, Life, or Travel.", "invalid_category", PRODUCT_CHOICES)
        if step in {"age", "coverage", "budget"}:
            return self.advisory_input(state, value)
        if step == "checklist_type":
            return self.public_checklist(state, value)
        if step == "policy_number":
            number = text.strip().upper()
            if not re.fullmatch(r"POL-[A-Z]{3}-\d{4}", number, re.ASCII):
                return Reply("Use the format POL-ABC-1234. You can find a sample under Demo records.",
                             "invalid_policy_format")
            state.draft["policy_number"] = number
            state.step = "mobile"
            return Reply("Enter the 10-digit demo mobile linked to this policy.", "ask_mobile")
        if step == "mobile":
            mobile = re.sub(r"[\s()-]", "", text.strip())
            if mobile.startswith("+91"):
                mobile = mobile[3:]
            if not re.fullmatch(r"[0-9]{10}", mobile):
                return Reply("Enter a 10-digit mobile from Demo records.", "invalid_mobile")
            policy = self.repository.policy(state.draft["policy_number"])
            matched = policy is not None and hmac.compare_digest(policy["demo_mobile"], mobile)
            state.draft["matched_mobile"] = bool(matched)
            return self.issue_otp(state)
        if step == "otp":
            return self.verify_otp(state, value)
        if step == "claim_reference":
            return self.claim_status(state, text.strip().upper())
        if step == "support_topic":
            return self.handoff(state, value)
        return self.claim_input(state, step, text, value)

    def advisory_input(self, state: Conversation, value: str) -> Reply:
        step = state.step
        limits = {"age": (18, 90), "coverage": (1, 100), "budget": (100, 100_000)}
        low, high = limits[step]
        number = int(value) if re.fullmatch(r"[0-9]{1,6}", value) else 0
        if not low <= number <= high:
            return Reply(f"Enter a whole number between {low:,} and {high:,}.", f"invalid_{step}")
        state.draft[step] = number
        if step == "age":
            state.step = "coverage"
            return Reply("Enter the minimum cover in lakh rupees. For ₹5 lakh, enter 5.",
                         "ask_coverage")
        if step == "coverage":
            state.step = "budget"
            return Reply("Enter your maximum monthly budget in rupees. For example, 1200.",
                         "ask_budget")

        slots = state.draft
        plans = eligible_plans(slots["category"], slots["age"], slots["coverage"], slots["budget"])
        state.clear()
        if not plans:
            return menu_reply("No sample plan meets all three inputs. Try another comparison "
                              "or ask the support desk.", "advisory_no_match")
        return Reply(
            "These sample plans match your age, cover and budget. The amounts are illustrative.",
            "advisory_complete", MENU,
            card=card("Matching sample plans", [
                (plan.name, f"₹{plan.cover_lakh} lakh cover · {format_inr(plan.monthly_inr)}/month")
                for plan in plans
            ]),
        )

    def public_checklist(self, state: Conversation, value: str) -> Reply:
        category = state.draft["category"]
        claim_type = self.pick(value, PRODUCTS[category].claims)
        if claim_type is None:
            return Reply("Choose one of the claim types shown.", "invalid_claim_type",
                         PRODUCTS[category].claims)
        state.clear()
        return Reply(f"Sample document checklist for {claim_type.lower()}.",
                     "checklist_complete", MENU, required_documents(category, claim_type))

    def otp_digest(self, state: Conversation, code: str) -> bytes:
        context = f"{state.key}|{state.draft_id}|{state.draft['policy_number']}|{code}"
        return hmac.digest(self.otp_key, context.encode(), "sha256")

    def issue_otp(self, state: Conversation) -> Reply:
        now = monotonic()
        if state.otp and now - state.otp.issued < 15:
            return Reply("Wait 15 seconds after issuance before requesting another code.",
                         "otp_cooldown", ("Resend code",))
        while state.otp_issues and now - state.otp_issues[0] > 300:
            state.otp_issues.popleft()
        if len(state.otp_issues) >= 4:
            return Reply("The verification limit was reached. Wait up to five minutes to retry.",
                         "otp_rate_limited")
        state.otp_issues.append(now)
        code = f"{secrets.randbelow(1_000_000):06d}"
        delivered = code if state.draft["matched_mobile"] else None
        state.otp = Challenge(self.otp_digest(state, code), delivered, now)
        state.step = "otp"
        self.repository.audit(state.key, state.flow, "otp_challenge_created")
        return Reply(
            "If the policy and mobile match, a six-digit code appears in Demo inbox. "
            "Enter it within three minutes.",
            "ask_otp", ("Resend code",),
        )

    def verify_otp(self, state: Conversation, value: str) -> Reply:
        if value == "resend code":
            return self.issue_otp(state)
        challenge = state.otp
        if challenge is None or monotonic() - challenge.issued >= OTP_TTL:
            return Reply("That code has expired. Choose Resend code to request a new one.",
                         "otp_expired", ("Resend code",))
        if not re.fullmatch(r"[0-9]{6}", value):
            return Reply("Enter a six-digit verification code.", "otp_invalid_format",
                         ("Resend code",))
        valid = hmac.compare_digest(challenge.digest, self.otp_digest(state, value))
        if not (valid and challenge.demo_code is not None):
            challenge.attempts -= 1
            self.repository.audit(state.key, state.flow, "otp_rejected")
            if challenge.attempts == 0:
                state.clear()
                return menu_reply("Verification ended after three incorrect attempts. "
                                  "Start a new request to try again.", "otp_locked")
            return Reply(f"Code not accepted. Attempts remaining: {challenge.attempts}.",
                         "otp_rejected", ("Resend code",))

        state.otp = None
        state.verified_policy = state.draft["policy_number"]
        state.verified_until = monotonic() + VERIFY_TTL
        self.repository.audit(state.key, state.flow, "otp_verified")
        return self.after_verification(state)

    def authorized(self, state: Conversation) -> bool:
        return (state.verified_policy is not None
                and state.verified_policy == state.draft.get("policy_number")
                and monotonic() < state.verified_until)

    def expire_verification(self, state: Conversation) -> Reply | None:
        if state.step in VERIFIED_STEPS and not self.authorized(state):
            state.clear()
            return menu_reply("Verification expired. Start the request again to continue.",
                              "verification_expired")
        return None

    def after_verification(self, state: Conversation) -> Reply:
        policy = self.repository.policy(state.verified_policy)
        if state.flow == "claim_status":
            state.step = "claim_reference"
            return Reply("Policy verified. Enter the claim reference from your acknowledgement.",
                         "ask_claim_reference")
        if state.flow == "claim_intimation":
            category = policy["category"]
            state.draft["category"] = category
            state.step = "claim_type"
            return Reply("Policy verified. Choose the type of claim to register.",
                         "ask_claim_type", PRODUCTS[category].claims)
        number = mask_policy(policy["number"])
        if state.flow == "premium_due":
            rows = [("Renewal due", policy["renewal_due"]),
                    ("Annual premium", format_inr(policy["premium_inr"]))]
            event = "premium_complete"
        else:
            rows = [("Plan", policy["plan"]), ("Cover", format_inr(policy["cover_inr"])),
                    ("Coverage period", f'{policy["starts"]} to {policy["ends"]}'),
                    ("Policy record", policy["status"])]
            event = "policy_complete"
        state.clear()
        return Reply("Here is the information from your verified demo policy.", event, MENU,
                     card=card(number, rows))

    def claim_status(self, state: Conversation, reference: str) -> Reply:
        if not re.fullmatch(r"CLM-[0-9A-F]{10}", reference):
            return Reply("Use the claim reference in the format CLM-0000001001.",
                         "invalid_claim_reference")
        claim = self.repository.claim(reference, state.verified_policy)
        if claim is None:
            return Reply("No matching claim was found for this verified policy. "
                         "Check the reference and try again.", "claim_not_found")

        state.clear()
        return Reply(
            "Here is the current status in the demo claims register.", "claim_status_complete",
            MENU, tuple(json.loads(claim["missing_documents"])),
            card("Claim " + claim["reference"], [
                ("Status", claim["status"]), ("Claim type", claim["claim_type"]),
                ("Incident date", claim["incident_date"]),
                ("Recorded on", claim["created_at"][:10]),
            ]),
        )

    def claim_input(self, state: Conversation, step: str, text: str, value: str) -> Reply:
        category = state.draft["category"]
        if step == "claim_type":
            claim_type = self.pick(value, PRODUCTS[category].claims)
            if claim_type is None:
                return Reply("Choose one of the listed claim types.", "invalid_claim_type",
                             PRODUCTS[category].claims)
            state.draft["claim_type"] = claim_type
            state.step = "incident_date"
            return Reply("Enter the incident date in YYYY-MM-DD format.", "ask_incident_date")
        if step == "incident_date":
            return self.set_incident_date(state, value)
        if step == "description":
            if not 12 <= len(text.strip()) <= 300:
                return Reply("Enter a demo incident description of 12 to 300 characters.",
                             "invalid_description")
            state.draft["description"] = text.strip()
            provider_prompt = PRODUCTS[category].provider_prompt
            if provider_prompt and state.draft["claim_type"] != "Vehicle theft":
                state.step = "provider"
                return Reply(provider_prompt, "ask_provider")
            return self.ask_documents(state)
        if step == "provider":
            if not 2 <= len(text.strip()) <= 80:
                return Reply("Enter a facility name of 2 to 80 characters.", "invalid_provider")
            state.draft["provider"] = text.strip()
            return self.ask_documents(state)
        if step == "documents":
            return self.set_document_readiness(state, value)
        if step == "confirmation":
            return self.confirm_claim(state, value)
        raise ValueError(f"Unknown workflow step: {step}")

    def set_incident_date(self, state: Conversation, value: str) -> Reply:
        try:
            if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
                raise ValueError
            incident = date.fromisoformat(value)
        except ValueError:
            return Reply("Enter a valid date in YYYY-MM-DD format.", "invalid_incident_date")
        if incident > date.today():
            return Reply("The incident date must be today or earlier.", "incident_in_future")

        policy = self.repository.policy(state.verified_policy)
        if not policy["starts"] <= incident.isoformat() <= policy["ends"]:
            return Reply("That date falls outside this policy's recorded coverage period. "
                         "Check the date or enter Cancel to return to the menu.",
                         "incident_outside_cover")
        state.draft["incident_date"] = incident.isoformat()
        state.step = "description"
        return Reply("Describe the fictional incident in one or two sentences.",
                     "ask_description")

    def ask_documents(
        self, state: Conversation, *,
        text: str = "Select the documents you have, or enter item numbers such as 1, 3.",
        event: str = "ask_documents",
    ) -> Reply:
        state.step = "documents"
        docs = required_documents(state.draft["category"], state.draft["claim_type"])
        return Reply(
            text, event, ("All ready", "None ready"),
            tuple(f"{i}. {document}" for i, document in enumerate(docs, start=1)),
        )

    def set_document_readiness(self, state: Conversation, value: str) -> Reply:
        docs = required_documents(state.draft["category"], state.draft["claim_type"])
        if value in {"all ready", "all"}:
            ready = set(range(1, len(docs) + 1))
        elif value in {"none ready", "none"}:
            ready = set()
        elif re.fullmatch(r"[1-9](?:\s*,\s*[1-9])*", value):
            ready = {int(number) for number in value.split(",")}
            if any(number > len(docs) for number in ready):
                return self.ask_documents(state, text=f"Choose item numbers from 1 to {len(docs)}.",
                                          event="invalid_document_selection")
        else:
            return self.ask_documents(state, text="Select the documents or enter item numbers like 1, 3.",
                                      event="invalid_document_selection")

        state.draft["missing_documents"] = [
            document for i, document in enumerate(docs, start=1) if i not in ready
        ]
        state.step = "confirmation"
        return self.claim_review(state, "Review the details and confirm to register this demo claim.",
                                 "ask_confirmation")

    def claim_review(self, state: Conversation, text: str, event: str) -> Reply:
        docs = required_documents(state.draft["category"], state.draft["claim_type"])
        missing = state.draft["missing_documents"]
        return Reply(
            text, event, ("Confirm claim", "Cancel"), tuple(missing),
            card("Review claim", [
                ("Policy", mask_policy(state.verified_policy)),
                ("Claim type", state.draft["claim_type"]),
                ("Incident date", state.draft["incident_date"]),
                ("Documents ready", f"{len(docs) - len(missing)} of {len(docs)}"),
            ]),
        )

    def confirm_claim(self, state: Conversation, value: str) -> Reply:
        if value not in {"confirm claim", "confirm"}:
            return self.claim_review(state, "Choose Confirm claim to register, or Cancel to discard the draft.",
                                     "confirmation_required")
        claim = self.repository.create_claim(state.key, state.draft_id, state.draft)
        state.clear()
        return Reply(
            "Claim intimation recorded. Use the reference below to track this claim.",
            "claim_registered", MENU, tuple(json.loads(claim["missing_documents"])),
            card(claim["reference"], [
                ("Status", claim["status"]),
                ("Claim type", claim["claim_type"]),
                ("Acknowledgement", "Recorded in the demo outbox"),
            ], tone="success"),
        )

    def handoff(self, state: Conversation, value: str) -> Reply:
        topic = self.pick(value, ("Policy", "Claim", "Other"))
        if topic is None:
            return Reply("Choose Policy, Claim, or Other.", "invalid_support_topic",
                         ("Policy", "Claim", "Other"))
        reference = self.repository.create_handoff(state.key, state.draft_id, topic)
        state.clear()
        return Reply("Your request was added to the local demo support queue.", "handoff_queued",
                     MENU, card=card(reference, [("Topic", topic), ("Status", "Queued")]))

    @staticmethod
    def pick(value: str, options: tuple[str, ...]) -> str | None:
        return next((option for option in options if option.casefold() == value), None)
