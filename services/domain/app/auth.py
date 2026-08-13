"""Identity resolution and access control.

Two kinds of bearer token reach this service, both signed with the shared secret:

- **User tokens** minted by auth-service (`role`: patient | admin) for the web portal.
- **Call session tokens** minted by agent-service (`role`: agent) for a live Call. These
  carry `patient_id` only once the Caller has completed Verification — an anonymous
  session has none, which is what makes the scheduling tools refuse to act.
"""
from dataclasses import dataclass

import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import Patient


@dataclass
class Principal:
    role: str  # patient | admin | agent
    user_id: int | None = None
    patient_id: int | None = None
    call_id: int | None = None


def get_principal(
    authorization: str = Header(default=""), db: Session = Depends(get_db)
) -> Principal:
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing bearer token")
    try:
        claims = jwt.decode(
            authorization.removeprefix("Bearer "),
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token")

    role = claims.get("role")
    if role == "agent":
        return Principal(
            role="agent",
            patient_id=claims.get("patient_id"),
            call_id=claims.get("call_id"),
        )
    if role not in ("patient", "admin"):
        raise HTTPException(403, "Unrecognised role")

    user_id = int(claims["sub"])
    patient_id = None
    if role == "patient":
        patient = db.scalar(select(Patient).where(Patient.user_id == user_id))
        patient_id = patient.id if patient else None
    return Principal(role=role, user_id=user_id, patient_id=patient_id)


def require_admin(principal: Principal = Depends(get_principal)) -> Principal:
    if principal.role != "admin":
        raise HTTPException(403, "Admin role required")
    return principal


def require_patient_identity(principal: Principal = Depends(get_principal)) -> Principal:
    """The caller must be acting as a known Patient — a linked portal account or a
    voice session that has completed Verification."""
    if principal.role == "admin":
        return principal
    if principal.patient_id is None:
        raise HTTPException(403, "Verification required before accessing patient records")
    return principal


def owns_or_admin(principal: Principal, patient_id: int) -> None:
    if principal.role != "admin" and principal.patient_id != patient_id:
        raise HTTPException(403, "Not your record")
