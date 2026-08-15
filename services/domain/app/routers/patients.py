from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import Principal, get_principal
from ..db import get_db
from ..models import Patient
from ..schemas import ClaimIn, PatientOut, RegisterPatientIn

router = APIRouter(prefix="/patients", tags=["patients"])


def normalize_phone(raw: str) -> str:
    """Accept whatever a person types — 555-010-0104, (555) 010 0104, +1 555… — and
    return the E.164 form records are stored in. Same rule the voice agent applies."""
    digits = "".join(c for c in raw if c.isdigit())
    if len(digits) == 10:
        digits = f"1{digits}"
    return f"+{digits}"


@router.get("/me", response_model=PatientOut)
def me(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    if principal.patient_id is None:
        raise HTTPException(404, "No patient record linked to this account")
    return db.get(Patient, principal.patient_id)


@router.post("/claim", response_model=PatientOut)
def claim(
    body: ClaimIn,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    """Link a portal account to its clinic record. Phone plus date of birth must both
    match, and a record already claimed by another account cannot be taken over."""
    if principal.role != "patient":
        raise HTTPException(403, "Only patient accounts can claim a record")
    patient = db.scalar(select(Patient).where(Patient.phone == normalize_phone(body.phone)))
    if patient is None or patient.dob != body.dob:
        raise HTTPException(404, "No patient record matches that phone number and date of birth")
    if patient.user_id is not None and patient.user_id != principal.user_id:
        raise HTTPException(
            409, "That record is already linked to another account — try a different patient"
        )
    patient.user_id = principal.user_id
    db.commit()
    db.refresh(patient)
    return patient


@router.post("/register", response_model=PatientOut, status_code=201)
def register(
    body: RegisterPatientIn,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    """Create a clinic record for a first-time Caller. Reachable by a live voice session
    or an admin — never by an ordinary portal account."""
    if principal.role not in ("agent", "admin"):
        raise HTTPException(403, "Not permitted")
    phone = normalize_phone(body.phone)
    if db.scalar(select(Patient).where(Patient.phone == phone)) is not None:
        raise HTTPException(409, "A patient with that phone number already exists")
    patient = Patient(
        first_name=body.first_name,
        last_name=body.last_name,
        dob=body.dob,
        phone=phone,
    )
    db.add(patient)
    db.commit()
    db.refresh(patient)
    return patient
