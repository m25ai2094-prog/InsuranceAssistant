"""Fictional plan catalog and controlled document checklists."""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Plan:
    name: str
    cover_lakh: int
    monthly_inr: int
    minimum_age: int
    maximum_age: int


@dataclass(frozen=True)
class Product:
    label: str
    claims: tuple[str, ...]
    documents: tuple[str, ...]
    plans: tuple[Plan, ...]
    provider_prompt: str = ""


PRODUCTS = {
    "health": Product(
        "Health",
        ("Hospitalisation", "Day-care treatment"),
        ("Claim form", "Discharge or treatment summary", "Itemised bills and receipts",
         "Investigation reports"),
        (Plan("Health Essentials", 5, 750, 18, 65),
         Plan("Health Plus", 10, 1450, 18, 70)),
        "Enter the name of the demo hospital or clinic.",
    ),
    "motor": Product(
        "Motor",
        ("Accidental damage", "Vehicle theft"),
        ("Claim form", "Vehicle registration certificate", "Driving licence",
         "Damage photos and repair estimate"),
        (Plan("Motor Essentials", 3, 490, 18, 80),
         Plan("Motor Plus", 7, 960, 18, 80)),
        "Enter the name of the demo repair workshop.",
    ),
    "life": Product(
        "Life",
        ("Death benefit", "Maturity benefit"),
        ("Claim form", "Policy schedule", "Claimant identity proof", "Death certificate"),
        (Plan("Term Essentials", 25, 790, 18, 60),
         Plan("Term Plus", 50, 1290, 18, 65)),
    ),
    "travel": Product(
        "Travel",
        ("Baggage loss", "Trip interruption"),
        ("Claim form", "Travel itinerary", "Carrier incident report", "Expense receipts"),
        (Plan("Travel Essentials", 3, 350, 18, 75),
         Plan("Travel Plus", 8, 850, 18, 80)),
    ),
}

SPECIAL_DOCUMENTS = {
    "Vehicle theft": (
        "Claim form", "Vehicle registration certificate", "Police report",
        "Vehicle key declaration",
    ),
    "Maturity benefit": (
        "Discharge form", "Policy schedule", "Policyholder identity proof",
        "Bank mandate",
    ),
    "Trip interruption": (
        "Claim form", "Travel itinerary", "Carrier cancellation notice",
        "Expense receipts",
    ),
}
CATEGORY_PATTERNS = {
    "health": r"health|medical|hospitali[sz]ation",
    "motor": r"motor|car|vehicle|bike|two[ -]wheeler",
    "life": r"life|term",
    "travel": r"travel|trip",
}


def category_from_text(text: str) -> str | None:
    matches = [
        key for key, pattern in CATEGORY_PATTERNS.items()
        if re.search(rf"\b(?:{pattern})\b", text, re.IGNORECASE)
    ]
    return matches[0] if len(matches) == 1 else None


def required_documents(category: str, claim_type: str = "") -> tuple[str, ...]:
    return SPECIAL_DOCUMENTS.get(claim_type, PRODUCTS[category].documents)


def eligible_plans(category: str, age: int, cover: int, budget: int) -> list[Plan]:
    """Filter the sample catalog by all three user constraints."""
    return sorted(
        (
            plan for plan in PRODUCTS[category].plans
            if plan.minimum_age <= age <= plan.maximum_age
            and plan.cover_lakh >= cover
            and plan.monthly_inr <= budget
        ),
        key=lambda plan: (plan.monthly_inr, -plan.cover_lakh, plan.name),
    )
