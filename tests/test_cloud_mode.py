"""Smoke tests for the low-memory cloud application mode."""
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from insurance.light_nlu import classify_message
from insurance.web import create_app


class LightweightIntentTests(unittest.TestCase):
    def test_supported_intents(self):
        cases = {
            "Hello there": "greet",
            "Recommend a health plan for me": "insurance_advisory",
            "Show me the claim document checklist": "document_checklist",
            "I need to register a claim": "claim_intimation",
            "Track my existing claim": "claim_status",
            "Check my premium due date": "premium_due",
            "View my policy details": "policy_details",
            "I want to talk to a person": "human_handoff",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                intent, confidence, _ = classify_message(text)
                self.assertEqual(intent, expected)
                self.assertGreater(confidence, 0)

    def test_category_entity(self):
        intent, _, entities = classify_message("Recommend a motor insurance plan")
        self.assertEqual(intent, "insurance_advisory")
        self.assertEqual(entities, [{"entity": "product_category", "value": "motor"}])


class LightweightAppTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db = Path(self.tmp.name) / "demo.sqlite3"
        self.app = create_app(db, lightweight=True)
        self.app.testing = True
        self.client = self.app.test_client()
        self.client.get("/api/session")

    def tearDown(self):
        self.tmp.cleanup()

    def chat(self, text):
        return self.client.post("/api/chat", json={"text": text, "request_id": str(uuid4())})

    def test_health_does_not_require_rasa(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["status"], "ready")
        self.assertIn("Lightweight", response.json["model"])

    def test_advisory_workflow(self):
        response = self.chat("Recommend a health insurance plan")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["event"], "ask_age")
        self.assertEqual(response.json["step"], "age")
        self.assertEqual(response.json["last_model"]["source"], "lightweight_rules")
        self.assertEqual(self.chat("30").json["step"], "coverage")
        self.assertEqual(self.chat("5").json["step"], "budget")
        self.assertEqual(self.chat("1200").json["event"], "advisory_complete")

    def test_policy_flow_starts(self):
        response = self.chat("View my policy details")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["event"], "ask_policy")
        self.assertEqual(response.json["step"], "policy_number")

    def test_document_checklist(self):
        response = self.chat("Show the claim document checklist for motor")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["step"], "checklist_type")
        self.assertEqual(response.json["flow"], "document_checklist")


if __name__ == "__main__":
    unittest.main()
