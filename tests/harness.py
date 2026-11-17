"""Helpers for exercising the actual local services on isolated ports."""

import json
import os
import signal
import socket
import subprocess
import sys
from contextlib import contextmanager
from http.cookiejar import CookieJar
from pathlib import Path
from time import monotonic, sleep
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


class Client:
    def __init__(self, base: str):
        self.base = base
        self.opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()))
        self.latencies = []

    def request(self, path: str, body: dict | None = None, *, status: int = 200, method=None):
        request = Request(
            self.base + path, data=None if body is None else json.dumps(body).encode(),
            headers={"Content-Type": "application/json"} if body is not None else {}, method=method,
        )
        try:
            with self.opener.open(request, timeout=25) as response:
                actual = response.status
                data = json.load(response)
        except HTTPError as error:
            actual = error.code
            data = json.load(error)
        assert actual == status, (path, actual, status, data.get("error"))
        return data

    def start(self):
        return self.request("/api/session")

    def turn(self, text: str, event: str | None = None, *, request_id=None, record=True):
        started = monotonic()
        result = self.request("/api/chat", {"text": text, "request_id": request_id or str(uuid4())})
        if record:
            self.latencies.append((monotonic() - started) * 1000)
        if event is not None:
            assert result["event"] == event, (event, result["event"], result["text"])
        return result

    def otp(self):
        return self.request("/api/demo-inbox")["code"]


def free_ports():
    with socket.socket() as first, socket.socket() as second:
        first.bind(("127.0.0.1", 0))
        second.bind(("127.0.0.1", 0))
        return first.getsockname()[1], second.getsockname()[1]


@contextmanager
def local_app(database: Path, python=sys.executable):
    web_port, rasa_port = free_ports()
    base = f"http://127.0.0.1:{web_port}"
    database.parent.mkdir(parents=True, exist_ok=True)
    launch_log = database.parent / "launch.log"
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    with launch_log.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [str(python), str(ROOT / "run.py"), "--port", str(web_port), "--rasa-port",
             str(rasa_port), "--db", str(database)],
            cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, creationflags=flags,
        )
        try:
            deadline = monotonic() + 100
            client = Client(base)
            while monotonic() < deadline and process.poll() is None:
                try:
                    client.request("/api/health")
                    break
                except (URLError, AssertionError):
                    sleep(0.25)
            else:
                service_log = database.parent / "rasa.log"
                details = service_log.read_text(encoding="utf-8")[-3500:] if service_log.exists() else ""
                raise RuntimeError(launch_log.read_text(encoding="utf-8") + details)
            yield base
        finally:
            if process.poll() is None:
                try:
                    process.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGINT)
                    process.wait(timeout=12)
                except (OSError, subprocess.TimeoutExpired):
                    process.kill()
                    process.wait()
