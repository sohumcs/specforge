"""Regenerate the curated sample blueprints used by the landing page and DemoProvider.

    cd backend && python scripts/generate_samples.py            # all samples
    cd backend && python scripts/generate_samples.py fintech    # one sample

Runs the real LLM chain (needs GEMINI_API_KEY and/or GROQ_API_KEY in backend/.env),
validates the result, and writes app/llm/demo_data/<slug>.json. Review the diff
before committing: these files are what visitors see first.
"""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.llm.breaker import MemoryBreaker
from app.llm.chain import default_providers, generate_draft
from app.llm.schemas import cross_reference_errors, to_graph
from app.nlp.brief import analyze

OUT = Path(__file__).resolve().parent.parent / "app" / "llm" / "demo_data"

SAMPLES = {
    "food-delivery": {
        "title": "Food delivery marketplace",
        "keywords": [
            "food",
            "delivery",
            "restaurant",
            "restaurants",
            "rider",
            "riders",
            "meal",
            "meals",
            "menu",
            "menus",
        ],
        "brief": (
            "A food delivery marketplace for a mid-sized city. Customers browse nearby "
            "restaurants, filter by cuisine and rating, build a cart, pay online by card or "
            "UPI, and track their rider live on a map. Restaurants manage menus, opening hours "
            "and item availability, and accept or reject incoming orders. Riders go online, "
            "receive delivery offers, pick up orders and mark them delivered. Admins handle "
            "refunds, disputes and restaurant onboarding. The app must cope with dinner-time "
            "peaks and keep payment data secure."
        ),
    },
    "hospital-appointments": {
        "title": "Hospital appointment system",
        "keywords": [
            "hospital",
            "patient",
            "patients",
            "doctor",
            "doctors",
            "appointment",
            "appointments",
            "clinic",
            "prescription",
            "receptionist",
        ],
        "brief": (
            "An appointment system for a multi-speciality hospital. Patients register, search "
            "doctors by speciality, see available slots and book, reschedule or cancel "
            "appointments, and receive SMS and email reminders. Receptionists manage doctor "
            "schedules, leave and walk-in queues. Doctors see their daily list, view patient "
            "history and write e-prescriptions. Patient records are confidential and access "
            "must be audited. The hospital wants fewer no-shows and shorter waiting times."
        ),
    },
    "college-erp": {
        "title": "College ERP",
        "keywords": [
            "college",
            "student",
            "students",
            "faculty",
            "course",
            "courses",
            "attendance",
            "exam",
            "exams",
            "timetable",
            "fee",
            "fees",
        ],
        "brief": (
            "An ERP for an engineering college with 5,000 students. Admins manage departments, "
            "courses, sections and timetables. Students enrol in electives, view timetables, "
            "pay semester fees online, download fee receipts and see exam results. Faculty "
            "mark attendance per lecture, upload internal marks and publish assignments. "
            "Parents get attendance and result notifications. Results day sees huge traffic "
            "spikes, and marks must never be editable after publication."
        ),
    },
    "fintech-wallet": {
        "title": "Fintech digital wallet",
        "keywords": [
            "wallet",
            "payment",
            "payments",
            "transfer",
            "transfers",
            "kyc",
            "bank",
            "money",
            "balance",
            "merchant",
            "fintech",
            "upi",
        ],
        "brief": (
            "A digital wallet app. Users sign up with phone number and complete KYC with ID "
            "documents, add money from their bank account, send money to contacts, pay "
            "merchants by scanning a QR code and view their transaction history and monthly "
            "statements. Merchants receive payments and request settlements to their bank. "
            "A compliance team reviews flagged transactions for fraud and enforces daily "
            "limits. Every transaction must be exactly-once, auditable and reconciled daily."
        ),
    },
}


def main(only: list[str]) -> None:
    providers = default_providers()
    for slug, spec in SAMPLES.items():
        if only and not any(o in slug for o in only):
            continue
        print(f"generating {slug} ...", flush=True)
        res = generate_draft(
            spec["brief"], analyze(spec["brief"]), providers=providers, breaker=MemoryBreaker()
        )
        if res.provider in ("demo", "cache"):
            raise SystemExit(f"{slug}: no LLM available ({res.attempts}); not overwriting")
        d = res.draft
        problems = cross_reference_errors(d.requirements, d.design, d.tests)
        if problems:
            raise SystemExit(f"{slug}: inconsistent output: {problems}")
        nodes, edges = to_graph(d)
        record = {
            "slug": slug,
            "title": spec["title"],
            "brief": spec["brief"],
            "keywords": spec["keywords"],
            "generated_by": res.provider,
            "stage_providers": res.stage_providers,
            "generated_at": datetime.now(UTC).date().isoformat(),
            "draft": d.model_dump(),
        }
        (OUT / f"{slug}.json").write_text(
            json.dumps(record, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"  {res.provider}: {len(nodes)} nodes, {len(edges)} edges")


if __name__ == "__main__":
    main(sys.argv[1:])
