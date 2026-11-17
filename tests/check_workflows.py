"""Run executable acceptance checks against the bundled model and SQLite."""

import argparse
import json
import math
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

from insurance.repository import DEMO_CLAIM, POLICIES, Repository
from insurance.workflow import Conversation, Workflow
from .harness import Client, ROOT, local_app


def check(output):
    results = []
    clients = []

    def passed(title, description):
        results.append({"scenario": title, "observed": description, "status": "PASS"})
        print(f"PASS  {title}", flush=True)

    def client(base):
        instance = Client(base)
        clients.append(instance)
        instance.start()
        return instance

    def authenticate(instance, utterance, policy_index, next_event):
        policy, phone, *_ = POLICIES[policy_index]
        instance.turn(utterance, "ask_policy")
        instance.turn(policy, "ask_mobile")
        instance.turn(phone, "ask_otp")
        code = instance.otp()
        assert code and len(code) == 6
        return instance.turn(code, next_event)

    with TemporaryDirectory(prefix="insurance-check-") as directory:
        database = Path(directory) / "insurance.sqlite3"
        incident = min(date.today() - timedelta(days=2), date(2030, 12, 31)).isoformat()
        with local_app(database) as base:
            raw = Client(base)
            assert raw.request("/api/health")["status"] == "ready"
            raw.request("/api/chat", {"text": "hello", "request_id": str(uuid4())}, status=401)
            raw.request("/internal/rasa/action", {"next_action": "action_insurance_workflow"},
                        status=403)
            raw.start()
            raw.request("/api/chat", {"text": "/provide_input", "request_id": str(uuid4())},
                        status=400)
            passed("Service startup and protected endpoints",
                   "Both services started. Anonymous chat, unsigned callback, and raw command were rejected.")

            advisory = client(base)
            reply = advisory.turn("Could you recommend a health plan for me?", "ask_age")
            assert reply["last_model"]["intent"] == "insurance_advisory"
            advisory.turn("12", "invalid_age")
            advisory.turn("30", "ask_coverage")
            advisory.turn("5", "ask_budget")
            reply = advisory.turn("1200", "advisory_complete")
            assert reply["card"]["rows"][0][0] == "Health Essentials"
            passed("Advisory with entity extraction",
                   "Health was extracted, age 12 was rejected, and ₹5 lakh within ₹1,200 returned Health Essentials.")

            advisory.turn("Recommend a policy", "ask_category")
            advisory.turn("Life", "ask_age")
            advisory.turn("40", "ask_coverage")
            advisory.turn("100", "ask_budget")
            advisory.turn("100", "advisory_no_match")
            passed("Advisory no-match branch", "A cover and budget outside the catalog returned no match.")

            docs = client(base)
            docs.turn("What supporting paperwork should I collect for a motor claim?",
                      "ask_checklist_type")
            reply = docs.turn("Vehicle theft", "checklist_complete")
            assert "Police report" in reply["items"]
            passed("Product-specific document checklist", "The motor theft checklist included a police report.")

            policy = client(base)
            policy.turn("Show my policy details", "ask_policy")
            policy.turn("not a policy", "invalid_policy_format")
            policy.turn(POLICIES[0][0], "ask_mobile")
            policy.turn("12", "invalid_mobile")
            reply = policy.turn(POLICIES[0][1], "ask_otp")
            assert reply["card"] is None and "Health Plus" not in reply["text"]
            code = policy.otp()
            assert code and client(base).otp() is None
            policy.turn("12", "otp_invalid_format")
            wrong = f"{(int(code) + 1) % 1_000_000:06d}"
            policy.turn(wrong, "otp_rejected")
            reply = policy.turn(code, "policy_complete")
            assert reply["card"]["title"] == "Policy ending in 1001"
            assert reply["card"]["rows"][0][1] == "Health Plus"
            assert policy.otp() is None
            passed("Policy details, OTP validation and inbox isolation",
                   "Wrong formats and a wrong code were rejected. Only the originating session saw the code.")

            unknown = client(base)
            unknown.turn("View my policy", "ask_policy")
            unknown.turn("POL-XYZ-9999", "ask_mobile")
            reply_unknown = unknown.turn("0000001001", "ask_otp")
            assert unknown.otp() is None
            wrong_phone = client(base)
            wrong_phone.turn("View my policy", "ask_policy")
            wrong_phone.turn(POLICIES[0][0], "ask_mobile")
            reply_wrong = wrong_phone.turn("0000001009", "ask_otp")
            assert wrong_phone.otp() is None and reply_unknown["text"] == reply_wrong["text"]
            passed("Unknown policy and mismatched mobile",
                   "Both produced the same prompt and no delivered demo code.")

            lockout = client(base)
            lockout.turn("Check premium due", "ask_policy")
            lockout.turn(POLICIES[0][0], "ask_mobile")
            lockout.turn(POLICIES[0][1], "ask_otp")
            old = lockout.otp()
            wrong = f"{(int(old) + 1) % 1_000_000:06d}"
            lockout.turn(wrong, "otp_rejected")
            lockout.turn(wrong, "otp_rejected")
            lockout.turn(wrong, "otp_locked")
            assert lockout.otp() is None
            passed("Three wrong codes end verification", "No policy or premium data was exposed.")

            premium = authenticate(client(base), "When is my next premium due?", 0, "premium_complete")
            assert ["Annual premium", "₹17,400"] in premium["card"]["rows"]
            passed("Verified premium enquiry", "The sample record returned the annual premium and due date.")

            tracking = client(base)
            authenticate(tracking, "Track a claim", 0, "ask_claim_reference")
            tracking.turn("123", "invalid_claim_reference")
            assert ["Status", "Under review"] in tracking.turn(
                DEMO_CLAIM, "claim_status_complete")["card"]["rows"]
            passed("Verified seed claim tracking", "The health policy owner retrieved the seeded Under review claim.")

            other = client(base)
            authenticate(other, "Check my claim status", 1, "ask_claim_reference")
            other.turn(DEMO_CLAIM, "claim_not_found")
            other.turn("Cancel", "workflow_cancelled")
            passed("Cross-policy claim lookup denied",
                   "The seeded health claim could not be read after verifying the motor policy.")

            claim = client(base)
            authenticate(claim, "Register a claim", 0, "ask_claim_type")
            claim.turn("Hospitalisation", "ask_incident_date")
            claim.turn("2026-02-31", "invalid_incident_date")
            claim.turn((date.today() + timedelta(days=1)).isoformat(), "incident_in_future")
            claim.turn("2023-01-01", "incident_outside_cover")
            claim.turn(incident, "ask_description")
            description = "A fictional hospital admission for the test case QA-HEALTH-INTAKE."
            assert claim.turn(description, "ask_provider")["echo"] == "[Incident description entered]"
            claim.turn("Demo City Hospital", "ask_documents")
            invalid_docs = claim.turn("8", "invalid_document_selection")
            assert len(invalid_docs["items"]) == 4
            assert claim.start()["message"]["items"] == invalid_docs["items"]
            review = claim.turn("1, 3", "ask_confirmation")
            assert ["Documents ready", "2 of 4"] in review["card"]["rows"]
            invalid_confirmation = claim.turn("show the draft again", "confirmation_required")
            assert invalid_confirmation["card"] == review["card"]
            assert claim.start()["message"]["card"] == review["card"]
            with closing(sqlite3.connect(database)) as db:
                assert db.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 1
            passed("Claim validations and confirmation boundary",
                   "Malformed, future and uncovered dates were blocked. Review left the database unchanged.")

            request_id = str(uuid4())
            with ThreadPoolExecutor(max_workers=2) as executor:
                submits = [executor.submit(claim.turn, "Confirm claim", "claim_registered",
                                           request_id=request_id, record=False) for _ in range(2)]
                first, second = [job.result() for job in submits]
            assert first == second
            new_claim = first["card"]["title"]
            assert ["Status", "Awaiting documents"] in first["card"]["rows"]
            with closing(sqlite3.connect(database)) as db:
                assert db.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 2
                assert db.execute("SELECT COUNT(*) FROM notifications WHERE claim_reference = ?",
                                  (new_claim,)).fetchone()[0] == 1
                assert db.execute("SELECT COUNT(*) FROM audit WHERE event = 'claim_registered'").fetchone()[0] == 1
            passed("Atomic claim registration and duplicate retry",
                   "Two concurrent requests with the same ID returned one reference, claim, outbox and audit row.")

            branch_cases = [
                (1, "Accidental damage", "Demo Auto Workshop"),
                (2, "Maturity benefit", None),
                (3, "Baggage loss", None),
            ]
            for index, claim_type, facility in branch_cases:
                branch = client(base)
                authenticate(branch, "File a new insurance claim", index, "ask_claim_type")
                branch.turn(claim_type, "ask_incident_date")
                branch.turn(incident, "ask_description")
                branch.turn("A fictional incident for an integration test.",
                            "ask_provider" if facility else "ask_documents")
                if facility:
                    branch.turn(facility, "ask_documents")
                branch.turn("All ready", "ask_confirmation")
                reply = branch.turn("Confirm claim", "claim_registered")
                assert ["Status", "Registered"] in reply["card"]["rows"]
            passed("Motor, life and travel claim branches",
                   "Motor asked for a workshop. Life and travel skipped the facility. Each registered a claim.")

            discarded = client(base)
            discarded.turn("Register a claim", "ask_policy")
            discarded.turn(POLICIES[0][0], "ask_mobile")
            discarded.turn("Cancel", "workflow_cancelled")
            assert discarded.otp() is None
            passed("Cancel clears the active draft", "Cancellation returned to the menu and discarded verification state.")

            support = client(base)
            support.turn("Talk to a person", "ask_support_topic")
            ticket = support.turn("Claim", "handoff_queued")["card"]["title"]
            with closing(sqlite3.connect(database)) as db:
                assert db.execute("SELECT topic FROM handoffs WHERE reference = ?", (ticket,)).fetchone() == ("Claim",)
            passed("Human handoff queue", "A local support record was queued with a reference and a topic.")

            fallback = client(base)
            fallback.turn("Tell me a joke", "nlu_fallback")
            reply = fallback.turn("What is the weather tomorrow?", "nlu_fallback")
            assert "Talk to a person" in reply["options"]
            passed("Out-of-scope recovery", "Repeated unrelated requests offered supported menu choices and handoff.")

            with closing(sqlite3.connect(database)) as db:
                audit = "\n".join(str(row) for row in db.execute("SELECT * FROM audit"))
                assert description not in audit and POLICIES[0][0] not in audit
                assert POLICIES[0][1] not in audit and new_claim not in audit
            rasa_log = (database.parent / "rasa.log").read_text(encoding="utf-8")
            assert description not in rasa_log and POLICIES[0][1] not in rasa_log
            passed("Audit and tracker input privacy",
                   "The audit and Rasa server log did not contain the sample description or demo mobile.")

        with local_app(database) as base:
            retriever = client(base)
            authenticate(retriever, "Track a claim", 0, "ask_claim_reference")
            tracked = retriever.turn(new_claim, "claim_status_complete")
            assert ["Status", "Awaiting documents"] in tracked["card"]["rows"]
            passed("Claim persisted across restart",
                   "A newly verified session found the claim written by the earlier server process.")

        clock = [100.0]
        with patch("insurance.workflow.monotonic", side_effect=lambda: clock[0]):
            flow = Workflow(Repository(database))
            state = Conversation("otp-expiry-fixture")
            flow.handle(state, "claim_status", "", [])
            flow.handle(state, "provide_input", POLICIES[0][0], [])
            flow.handle(state, "provide_input", POLICIES[0][1], [])
            expired_code = state.otp.demo_code
            clock[0] += 181
            assert flow.handle(state, "provide_input", expired_code, []).event == "otp_expired"
            assert flow.handle(state, "provide_input", "resend code", []).event == "ask_otp"
            assert flow.handle(state, "provide_input", state.otp.demo_code, []).event == "ask_claim_reference"
            clock[0] += 601
            assert flow.handle(state, "provide_input", DEMO_CLAIM, []).event == "verification_expired"
        passed("OTP expiry, resend and verification expiry",
               "A controlled clock exercised 180-second OTP expiry and the 600-second verified window.")

    samples = sorted(value for instance in clients for value in instance.latencies)
    report = {
        "checks": results,
        "passed": len(results),
        "latency_ms": {"n": len(samples), "p50": round(median(samples), 2),
                       "p95": round(samples[math.ceil(len(samples) * 0.95) - 1], 2)},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n{len(results)}/{len(results)} acceptance scenarios passed.")
    print(f"Loopback chat latency p50 / p95: {report['latency_ms']['p50']:.2f} / "
          f"{report['latency_ms']['p95']:.2f} ms across {len(samples)} measured turns.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "evidence" / "workflow_checks.json")
    check(parser.parse_args().output)
