"""Verification: proving a Caller is a Patient during a live conversation.

Delivery is mocked. Seeded patients carry fictional 555 numbers that no SMS can reach,
so a real one-time code is generated and surfaced on an admin-only debug endpoint
instead of being texted. Swapping in Twilio is a delivery-function change, nothing more.
"""
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import Principal, get_principal, require_admin
from ..db import get_db
from ..models import Patient, VerificationCode
from ..schemas import (
    VerificationConfirmIn,
    VerificationConfirmOut,
    VerificationRequestIn,
    VerificationRequestOut,
)

router = APIRouter(prefix="/verification", tags=["verification"])

CODE_TTL = timedelta(minutes=10)
MAX_ATTEMPTS = 5


def _mask(phone: str) -> str:
    return f"•••••{phone[-4:]}" if len(phone) >= 4 else "•••••"


def _require_agent(principal: Principal) -> None:
    if principal.role not in ("agent", "admin"):
        raise HTTPException(403, "Verification is driven by the voice agent")


@router.post("/request", response_model=VerificationRequestOut)
def request_code(
    body: VerificationRequestIn,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    _require_agent(principal)
    patient = db.scalar(select(Patient).where(Patient.phone == body.phone))
    if patient is None:
        # Deliberately not an error: Maya offers to register the caller instead.
        return VerificationRequestOut(
            sent=False,
            message="No patient record matches that number",
        )

    code = f"{secrets.randbelow(1_000_000):06d}"
    db.add(
        VerificationCode(
            patient_id=patient.id,
            call_id=body.call_id or principal.call_id,
            code=code,
            expires_at=datetime.now(timezone.utc) + CODE_TTL,
        )
    )
    db.commit()
    return VerificationRequestOut(
        sent=True,
        masked_phone=_mask(patient.phone),
        message=f"A six-digit code was sent to {_mask(patient.phone)}",
    )


@router.post("/confirm", response_model=VerificationConfirmOut)
def confirm_code(
    body: VerificationConfirmIn,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    _require_agent(principal)
    patient = db.scalar(select(Patient).where(Patient.phone == body.phone))
    if patient is None:
        raise HTTPException(404, "No patient record matches that number")

    record = db.scalars(
        select(VerificationCode)
        .where(
            VerificationCode.patient_id == patient.id,
            VerificationCode.consumed_at.is_(None),
        )
        .order_by(VerificationCode.created_at.desc())
        .limit(1)
    ).one_or_none()

    if record is None:
        return VerificationConfirmOut(verified=False, message="No pending code — request a new one")
    if record.expires_at < datetime.now(timezone.utc):
        return VerificationConfirmOut(verified=False, message="That code expired — request a new one")
    if record.attempts >= MAX_ATTEMPTS:
        return VerificationConfirmOut(verified=False, message="Too many attempts — request a new code")

    record.attempts += 1
    if not secrets.compare_digest(record.code, body.code.strip()):
        db.commit()
        return VerificationConfirmOut(verified=False, message="That code doesn't match")

    record.consumed_at = datetime.now(timezone.utc)
    db.commit()
    return VerificationConfirmOut(
        verified=True,
        patient_id=patient.id,
        first_name=patient.first_name,
        message="Verified",
    )


@router.get("/debug/recent")
def recent_codes(
    _: Principal = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Stands in for the patient's SMS inbox during the demo. Admin-only."""
    rows = db.scalars(
        select(VerificationCode).order_by(VerificationCode.created_at.desc()).limit(10)
    ).all()
    return [
        {
            "patient_id": r.patient_id,
            "phone": db.get(Patient, r.patient_id).phone,
            "code": r.code,
            "expires_at": r.expires_at,
            "consumed": r.consumed_at is not None,
        }
        for r in rows
    ]
