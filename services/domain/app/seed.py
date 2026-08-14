"""Idempotent mock-world seed for Assort Dermatology. All data is fictional — no real PII."""
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import FaqChunk, Patient, Provider, Slot, VisitType

PROVIDERS = [
    ("Dr. Elena Vasquez", "Dermatologist"),
    ("Dr. Marcus Chen", "Dermatologist"),
    ("Dr. Priya Raman", "Pediatric Dermatologist"),
    ("Dr. Samuel Okafor", "Dermatologic Surgeon"),
]

VISIT_TYPES = [("New Patient", 30), ("Follow-up", 15)]

# Fictional patients; 555-01xx numbers are reserved for fiction in the NANP
PATIENTS = [
    ("Ava", "Thompson", date(1991, 3, 14), "+15550100101"),
    ("Liam", "Garcia", date(1985, 7, 2), "+15550100102"),
    ("Noah", "Kim", date(1978, 11, 23), "+15550100103"),
    ("Emma", "Patel", date(1996, 1, 9), "+15550100104"),
    ("Olivia", "Nguyen", date(1989, 5, 30), "+15550100105"),
    ("Ethan", "Brooks", date(1972, 9, 17), "+15550100106"),
    ("Sophia", "Rivera", date(2001, 12, 5), "+15550100107"),
    ("Mason", "Clark", date(1983, 4, 21), "+15550100108"),
    ("Isabella", "Wright", date(1994, 8, 11), "+15550100109"),
    ("Lucas", "Hall", date(1968, 2, 28), "+15550100110"),
    ("Mia", "Young", date(1999, 6, 15), "+15550100111"),
    ("James", "Allen", date(1980, 10, 3), "+15550100112"),
    ("Charlotte", "King", date(1992, 3, 27), "+15550100113"),
    ("Ben", "Scott", date(1975, 7, 19), "+15550100114"),
    ("Amelia", "Torres", date(1987, 11, 8), "+15550100115"),
    ("Henry", "Adams", date(1965, 1, 31), "+15550100116"),
    ("Harper", "Baker", date(1998, 5, 12), "+15550100117"),
    ("Jack", "Cruz", date(1990, 9, 24), "+15550100118"),
    ("Evelyn", "Reed", date(1982, 12, 16), "+15550100119"),
    ("Leo", "Morgan", date(1995, 4, 7), "+15550100120"),
]

FAQS = [
    ("Clinic hours", "Assort Dermatology is open Monday through Friday, 9 AM to 5 PM. We are closed on weekends and federal holidays."),
    ("Location and parking", "We are located at 450 Harbor Lane, Suite 210. Free patient parking is available in the attached garage; bring your ticket for validation."),
    ("New patient visit", "New patient visits are 30 minutes. Please arrive 15 minutes early with a photo ID, your insurance card, and a list of current medications."),
    ("Follow-up visit", "Follow-up visits are 15 minutes and are for existing patients reviewing an ongoing condition or treatment."),
    ("Cancellation policy", "Appointments cancelled or rescheduled less than 24 hours before the visit require staff review and may incur a fee."),
    ("Skin check preparation", "For a full-body skin check, remove nail polish, wear loose clothing, and avoid heavy makeup so all skin areas can be examined."),
    ("Biopsy aftercare", "Keep the biopsy site covered and dry for 24 hours, then wash gently with soap and water and apply petroleum jelly daily until healed."),
    ("Insurance", "We accept most major PPO plans. Please contact your insurer to confirm coverage; copays are due at the time of the visit."),
    ("Prescription refills", "Refill requests are handled by your pharmacy or through the patient portal; the voice assistant cannot process refills."),
    ("Telehealth", "Selected follow-up visits may be conducted by video. Ask when booking whether your visit type qualifies."),
    ("Minors", "Patients under 18 must be accompanied by a parent or legal guardian for their appointment."),
    ("What to bring", "Bring a photo ID, your insurance card, a list of medications, and any relevant prior dermatology records."),
    ("Sunscreen advice", "We generally recommend broad-spectrum SPF 30 or higher for daily use. For personal medical advice, please book an appointment."),
    ("Results turnaround", "Biopsy results typically take 7 to 10 business days. A member of our clinical team will contact you with results."),
    ("Accessibility", "The clinic is wheelchair accessible, and service animals are welcome."),
]


def seed(db: Session) -> None:
    if db.scalar(select(Provider).limit(1)) is not None:
        return

    providers = [Provider(name=n, title=t) for n, t in PROVIDERS]
    visit_types = [VisitType(name=n, duration_minutes=d) for n, d in VISIT_TYPES]
    patients = [
        Patient(first_name=f, last_name=l, dob=dob, phone=phone)
        for f, l, dob, phone in PATIENTS
    ]
    db.add_all(providers + visit_types + patients)
    db.flush()

    new_patient, follow_up = visit_types
    today = datetime.now(timezone.utc).date()
    slots: list[Slot] = []

    # A few same-day/next-day slots pinned relative to *now*, so something is always
    # bookable within 24 hours no matter what hour or weekday the seed runs. The 24h
    # approval policy (and its demo, and its tests) depends on near-term slots existing.
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    for provider, hours_ahead in zip(providers, [3, 6, 12, 20]):
        slots.append(
            Slot(
                provider_id=provider.id,
                visit_type_id=follow_up.id,
                starts_at=now + timedelta(hours=hours_ahead),
            )
        )

    # Weekday slots for the next 14 days: mornings New Patient, afternoons Follow-up
    for day_offset in range(1, 15):
        day = today + timedelta(days=day_offset)
        if day.weekday() >= 5:
            continue
        for provider in providers:
            for hour, minute in [(9, 0), (9, 30), (10, 0), (10, 30), (11, 0), (11, 30)]:
                slots.append(
                    Slot(
                        provider_id=provider.id,
                        visit_type_id=new_patient.id,
                        starts_at=datetime.combine(day, time(hour, minute), tzinfo=timezone.utc),
                    )
                )
            for hour, minute in [(13, 0), (13, 15), (13, 30), (13, 45), (14, 0), (14, 15), (14, 30), (14, 45), (15, 0), (15, 15), (15, 30), (15, 45), (16, 0)]:
                slots.append(
                    Slot(
                        provider_id=provider.id,
                        visit_type_id=follow_up.id,
                        starts_at=datetime.combine(day, time(hour, minute), tzinfo=timezone.utc),
                    )
                )
    db.add_all(slots)

    db.add_all([FaqChunk(title=t, text=x) for t, x in FAQS])
    db.commit()
