"""SQLite storage for demo policies, claim intake, and audit records."""

import hashlib
import json
import secrets
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path


POLICIES = (
    ("POL-HLT-1001", "0000001001", "health", "Health Plus", 1_000_000,
     "2025-01-01", "2030-12-31", 17_400, "2027-01-01", "Active"),
    ("POL-MTR-1002", "0000001002", "motor", "Motor Plus", 700_000,
     "2025-01-01", "2030-12-31", 11_520, "2027-02-01", "Active"),
    ("POL-LIF-1003", "0000001003", "life", "Term Plus", 5_000_000,
     "2025-01-01", "2030-12-31", 15_480, "2027-03-01", "Active"),
    ("POL-TRV-1004", "0000001004", "travel", "Travel Plus", 800_000,
     "2025-01-01", "2030-12-31", 10_200, "2027-04-01", "Active"),
    ("POL-HLT-1005", "0000001005", "health", "Health Essentials", 500_000,
     "2023-01-01", "2024-12-31", 9_000, "2024-12-31", "Expired"),
)
DEMO_CLAIM = "CLM-0000001001"

SCHEMA = """
CREATE TABLE IF NOT EXISTS policies (
    number TEXT PRIMARY KEY, demo_mobile TEXT NOT NULL,
    category TEXT NOT NULL, plan TEXT NOT NULL, cover_inr INTEGER NOT NULL,
    starts TEXT NOT NULL, ends TEXT NOT NULL, premium_inr INTEGER NOT NULL,
    renewal_due TEXT NOT NULL, status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS claims (
    reference TEXT PRIMARY KEY, draft_id TEXT NOT NULL UNIQUE,
    policy_number TEXT NOT NULL REFERENCES policies(number),
    claim_type TEXT NOT NULL, incident_date TEXT NOT NULL,
    description TEXT NOT NULL, provider TEXT NOT NULL,
    missing_documents TEXT NOT NULL, status TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notifications (
    claim_reference TEXT PRIMARY KEY REFERENCES claims(reference),
    event TEXT NOT NULL, channel TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS handoffs (
    reference TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE,
    topic TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY, session_fingerprint TEXT NOT NULL,
    flow TEXT NOT NULL, event TEXT NOT NULL, created_at TEXT NOT NULL
);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Repository:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db, db:
            db.execute("PRAGMA journal_mode = WAL")
            db.executescript(SCHEMA)
            db.executemany("INSERT OR IGNORE INTO policies VALUES (?,?,?,?,?,?,?,?,?,?)", POLICIES)
            db.execute(
                "INSERT OR IGNORE INTO claims VALUES (?,?,?,?,?,?,?,?,?,?)",
                (DEMO_CLAIM, "seed-health-1", POLICIES[0][0], "Hospitalisation",
                 "2025-10-10", "Fictional intake record.", "Demo City Hospital",
                 "[]", "Under review", "2025-10-12T10:00:00+00:00"),
            )

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        return db

    @contextmanager
    def write(self):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            yield db

    def policy(self, number: str) -> sqlite3.Row | None:
        with closing(self.connect()) as db:
            return db.execute("SELECT * FROM policies WHERE number = ?", (number,)).fetchone()

    def claim(self, reference: str, policy_number: str) -> sqlite3.Row | None:
        with closing(self.connect()) as db:
            return db.execute(
                "SELECT * FROM claims WHERE reference = ? AND policy_number = ?",
                (reference, policy_number),
            ).fetchone()

    def _audit(self, db, session_key: str, flow: str, event: str):
        fingerprint = hashlib.sha256(session_key.encode()).hexdigest()[:24]
        db.execute(
            "INSERT INTO audit (session_fingerprint, flow, event, created_at) VALUES (?,?,?,?)",
            (fingerprint, flow, event, utc_now()),
        )

    def audit(self, session_key: str, flow: str, event: str):
        with self.write() as db:
            self._audit(db, session_key, flow, event)

    def create_claim(self, session_key: str, draft_id: str, draft: dict) -> sqlite3.Row:
        """Commit one claim and one acknowledgement per confirmed draft."""
        with self.write() as db:
            existing = db.execute("SELECT * FROM claims WHERE draft_id = ?", (draft_id,)).fetchone()
            if existing is not None:
                return existing

            reference = "CLM-" + secrets.token_hex(5).upper()
            created = utc_now()
            missing = draft["missing_documents"]
            status = "Awaiting documents" if missing else "Registered"
            db.execute(
                "INSERT INTO claims VALUES (?,?,?,?,?,?,?,?,?,?)",
                (reference, draft_id, draft["policy_number"], draft["claim_type"],
                 draft["incident_date"], draft["description"], draft.get("provider", ""),
                 json.dumps(missing), status, created),
            )
            db.execute(
                "INSERT INTO notifications VALUES (?,?,?,?)",
                (reference, "claim_acknowledgement", "simulated", created),
            )
            self._audit(db, session_key, "claim_intimation", "claim_registered")
            return db.execute("SELECT * FROM claims WHERE reference = ?", (reference,)).fetchone()

    def create_handoff(self, session_key: str, request_id: str, topic: str) -> str:
        with self.write() as db:
            prior = db.execute(
                "SELECT reference FROM handoffs WHERE request_id = ?", (request_id,)
            ).fetchone()
            if prior is not None:
                return prior["reference"]

            reference = "SUP-" + secrets.token_hex(5).upper()
            db.execute("INSERT INTO handoffs VALUES (?,?,?,?)",
                       (reference, request_id, topic, utc_now()))
            self._audit(db, session_key, "human_handoff", "handoff_queued")
            return reference
