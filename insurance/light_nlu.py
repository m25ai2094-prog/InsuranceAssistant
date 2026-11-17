"""Small deterministic intent router for low-memory cloud demonstrations.

This replaces only the Rasa/TensorFlow inference process in cloud mode.
The existing Workflow, repository, validation, OTP and claim logic are shared.
"""
from __future__ import annotations

import re

from .catalog import category_from_text

# Phrases are intentionally conservative and weighted. A tie falls back safely.
INTENT_PHRASES = {
    "human_handoff": (
        "talk to a person", "speak to a person", "human support", "live agent",
        "customer service", "support team", "talk to support", "representative",
        "contact support", "staff member", "speak to support", "human agent",
    ),
    "document_checklist": (
        "document checklist", "documents do i need", "documents required",
        "claim documents", "supporting documents", "claim paperwork",
        "what paperwork", "which papers", "documents for a claim", "claim form",
        "what evidence", "paperwork for", "documents should i",
    ),
    "claim_status": (
        "track a claim", "track my claim", "claim status", "status of my claim",
        "claim progress", "existing claim", "previous claim", "claim reference",
        "where is my claim", "has my claim", "update on my claim", "track claim",
    ),
    "claim_intimation": (
        "register a claim", "file a claim", "make a claim", "new claim",
        "start a claim", "submit a claim", "lodge a claim", "claim for an accident",
        "report an incident", "report a new loss", "begin claim intimation",
        "claim application", "claim request", "raise a claim",
    ),
    "premium_due": (
        "premium due", "premium payment", "renewal date", "renewal amount",
        "next premium", "when do i renew", "premium amount", "payment due",
        "next instalment", "insurance bill", "renew my policy", "premium balance",
    ),
    "policy_details": (
        "view my policy", "policy details", "existing policy",
        "current policy", "policy summary", "policy coverage", "sum insured",
        "policy expiry", "policy expires", "coverage information", "show my cover",
    ),
    "insurance_advisory": (
        "recommend a policy", "recommend insurance", "insurance plan",
        "insurance plans", "recommend a plan", "compare plans", "compare insurance",
        "choose an insurance", "choose a plan", "buy insurance", "buy a policy",
        "insurance options", "plan for my budget", "suggest a policy", "policy recommendation",
    ),
    "greet": (
        "hello", "hi", "hey", "good morning", "good afternoon", "good evening",
        "how are you", "greetings", "good day", "howdy",
    ),
}


def _clean(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.casefold()))


def classify_message(text: str) -> tuple[str, float, list[dict]]:
    """Return (intent, heuristic confidence, entities) without ML dependencies."""
    clean = _clean(text)
    padded = f" {clean} "
    scores: dict[str, float] = {}
    for intent, phrases in INTENT_PHRASES.items():
        score = 0.0
        for phrase in phrases:
            phrase_clean = _clean(phrase)
            if f" {phrase_clean} " in padded:
                score = max(score, 0.92 + min(len(phrase_clean.split()), 4) * 0.015)
        scores[intent] = score

    # Additional single-term cues help with natural variations while avoiding
    # broad matches such as "claim" alone deciding between filing and tracking.
    if re.search(r"\b(track|tracking|status|progress|update)\b", clean):
        scores["claim_status"] = max(scores["claim_status"], 0.78)
    if re.search(r"\b(register|file|lodge|submit|initiate|raise)\b", clean) and "claim" in clean:
        scores["claim_intimation"] = max(scores["claim_intimation"], 0.80)
    if re.search(r"\b(checklist|paperwork|documents|evidence)\b", clean):
        scores["document_checklist"] = max(scores["document_checklist"], 0.80)
    if re.search(r"\b(premium|renewal|instalment|installment)\b", clean):
        scores["premium_due"] = max(scores["premium_due"], 0.76)
    if re.search(r"\b(policy|cover|coverage|covered|insured|sum insured)\b", clean):
        scores["policy_details"] = max(scores["policy_details"], 0.62)
    if re.search(r"\b(recommend|compare|suggest|buy|purchase|plan|insurance options)\b", clean) and not scores["document_checklist"]:
        scores["insurance_advisory"] = max(scores["insurance_advisory"], 0.72)
    if "insurance" in clean and category_from_text(clean) and not scores["document_checklist"]:
        scores["insurance_advisory"] = max(scores["insurance_advisory"], 0.74)
    if re.search(r"\b(agent|representative|person|human|support)\b", clean):
        scores["human_handoff"] = max(scores["human_handoff"], 0.74)

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    intent, score = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0.0
    if score == 0 or score - second < 0.08:
        intent, score = "nlu_fallback", 0.0

    category = category_from_text(clean)
    entities = ([{"entity": "product_category", "value": category}] if category else [])
    # The workflow has its own fallback response and validated step collection.
    return intent, round(min(score, 0.99), 2) if score else 0.0, entities
