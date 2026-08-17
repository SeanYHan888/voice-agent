import json
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import Principal, get_principal, owns_or_admin, require_patient_identity
from ..db import get_db
from ..models import AdminTask, Appointment, Patient, Provider, Slot, VisitType
from ..schemas import AppointmentOut, BookIn, ProviderOut, RescheduleIn, SlotOut

router = APIRouter(tags=["scheduling"])

# Changes inside this window need staff sign-off rather than executing immediately.
APPROVAL_WINDOW = timedelta(hours=24)


def _appointment_out(appt: Appointment, **extra) -> AppointmentOut:
    return AppointmentOut(
        id=appt.id,
        patient_id=appt.patient_id,
        status=appt.status,
        provider_name=appt.slot.provider.name,
        visit_type=appt.slot.visit_type.name,
        starts_at=appt.slot.starts_at,
        **extra,
    )


def _slot_out(s: Slot) -> SlotOut:
    return SlotOut(
        id=s.id,
        provider_id=s.provider_id,
        provider_name=s.provider.name,
        visit_type=s.visit_type.name,
        starts_at=s.starts_at,
    )


def _within_approval_window(starts_at: datetime) -> bool:
    return starts_at - datetime.now(timezone.utc) < APPROVAL_WINDOW


@router.get("/providers", response_model=list[ProviderOut])
def providers(db: Session = Depends(get_db)):
    return db.scalars(select(Provider).order_by(Provider.id)).all()


@router.get("/slots", response_model=list[SlotOut])
def slots(
    on: date | None = Query(default=None, description="Filter to a single day"),
    visit_type: str | None = None,
    provider_id: int | None = None,
    limit: int = Query(default=20, le=200),
    db: Session = Depends(get_db),
):
    """Open slot search. Deliberately unauthenticated — availability is public
    information, and Maya answers it before any Verification."""
    now = datetime.now(timezone.utc)
    q = (
        select(Slot)
        .join(VisitType)
        .where(Slot.status == "open", Slot.starts_at > now)
        .order_by(Slot.starts_at)
        .limit(limit)
    )
    if on is not None:
        day_start = datetime.combine(on, time.min, tzinfo=timezone.utc)
        q = q.where(Slot.starts_at >= day_start, Slot.starts_at < day_start + timedelta(days=1))
    if visit_type is not None:
        q = q.where(VisitType.name == visit_type)
    if provider_id is not None:
        q = q.where(Slot.provider_id == provider_id)

    return [_slot_out(s) for s in db.scalars(q).all()]


@router.get("/slots/calendar", response_model=list[SlotOut])
def slots_calendar(
    start: date = Query(description="First day of the window (UTC)"),
    days: int = Query(default=7, ge=1, le=14),
    visit_type: str | None = None,
    db: Session = Depends(get_db),
):
    """Every open slot in a short window, for the portal's availability calendar.
    Unlike /slots this is bounded by the window rather than a row limit, so a
    whole week of every provider comes back in one request. Public, like /slots."""
    now = datetime.now(timezone.utc)
    window_start = datetime.combine(start, time.min, tzinfo=timezone.utc)
    q = (
        select(Slot)
        .join(VisitType)
        .where(
            Slot.status == "open",
            Slot.starts_at > now,
            Slot.starts_at >= window_start,
            Slot.starts_at < window_start + timedelta(days=days),
        )
        .order_by(Slot.starts_at)
    )
    if visit_type is not None:
        q = q.where(VisitType.name == visit_type)
    return [_slot_out(s) for s in db.scalars(q).all()]


@router.post("/appointments", response_model=AppointmentOut, status_code=201)
def book(
    body: BookIn,
    principal: Principal = Depends(require_patient_identity),
    db: Session = Depends(get_db),
):
    patient_id = body.patient_id if principal.role == "admin" else principal.patient_id
    if patient_id is None:
        raise HTTPException(400, "patient_id is required when booking as admin")
    if db.get(Patient, patient_id) is None:
        raise HTTPException(404, "Unknown patient")

    # Lock the row so two concurrent callers cannot claim the same slot.
    slot = db.scalars(select(Slot).where(Slot.id == body.slot_id).with_for_update()).one_or_none()
    if slot is None:
        raise HTTPException(404, "Unknown slot")
    if slot.status != "open":
        raise HTTPException(409, "That time was just taken — please pick another")
    if slot.starts_at <= datetime.now(timezone.utc):
        raise HTTPException(409, "That time is in the past")

    slot.status = "booked"
    appt = Appointment(patient_id=patient_id, slot_id=slot.id, call_id=principal.call_id)
    db.add(appt)
    db.commit()
    db.refresh(appt)
    return _appointment_out(appt, message="Appointment booked")


@router.get("/appointments/me", response_model=list[AppointmentOut])
def my_appointments(
    principal: Principal = Depends(require_patient_identity),
    include_past: bool = False,
    db: Session = Depends(get_db),
):
    q = (
        select(Appointment)
        .join(Slot)
        .where(Appointment.patient_id == principal.patient_id)
        .order_by(Slot.starts_at)
    )
    if not include_past:
        q = q.where(Slot.starts_at > datetime.now(timezone.utc))
    return [_appointment_out(a) for a in db.scalars(q).all()]


@router.post("/appointments/{appointment_id}/cancel", response_model=AppointmentOut)
def cancel(
    appointment_id: int,
    principal: Principal = Depends(require_patient_identity),
    db: Session = Depends(get_db),
):
    appt = db.get(Appointment, appointment_id)
    if appt is None:
        raise HTTPException(404, "Unknown appointment")
    owns_or_admin(principal, appt.patient_id)
    if appt.status not in ("booked", "pending_change"):
        raise HTTPException(409, f"Appointment is {appt.status}")

    # Staff are the approvers, so their own cancellations don't queue for approval.
    if principal.role != "admin" and _within_approval_window(appt.slot.starts_at):
        appt.status = "pending_change"
        db.add(
            AdminTask(
                kind="approval",
                payload=json.dumps({"action": "cancel", "appointment_id": appt.id}),
                call_id=principal.call_id,
            )
        )
        db.commit()
        db.refresh(appt)
        return _appointment_out(
            appt,
            requires_approval=True,
            message="Within 24 hours of the visit, so a staff member will review this cancellation.",
        )

    appt.status = "cancelled"
    appt.slot.status = "open"
    db.commit()
    db.refresh(appt)
    return _appointment_out(appt, message="Appointment cancelled")


@router.post("/appointments/{appointment_id}/reschedule", response_model=AppointmentOut)
def reschedule(
    appointment_id: int,
    body: RescheduleIn,
    principal: Principal = Depends(require_patient_identity),
    db: Session = Depends(get_db),
):
    appt = db.get(Appointment, appointment_id)
    if appt is None:
        raise HTTPException(404, "Unknown appointment")
    owns_or_admin(principal, appt.patient_id)
    if appt.status != "booked":
        raise HTTPException(409, f"Appointment is {appt.status}")

    new_slot = db.scalars(
        select(Slot).where(Slot.id == body.new_slot_id).with_for_update()
    ).one_or_none()
    if new_slot is None:
        raise HTTPException(404, "Unknown slot")
    if new_slot.status != "open":
        raise HTTPException(409, "That time was just taken — please pick another")

    if _within_approval_window(appt.slot.starts_at):
        # The requested slot is re-validated when an admin approves, not held now.
        appt.status = "pending_change"
        db.add(
            AdminTask(
                kind="approval",
                payload=json.dumps(
                    {
                        "action": "reschedule",
                        "appointment_id": appt.id,
                        "new_slot_id": new_slot.id,
                    }
                ),
                call_id=principal.call_id,
            )
        )
        db.commit()
        db.refresh(appt)
        return _appointment_out(
            appt,
            requires_approval=True,
            message="Within 24 hours of the visit, so a staff member will review this change.",
        )

    old_slot = appt.slot
    old_slot.status = "open"
    new_slot.status = "booked"
    appt.slot_id = new_slot.id
    db.commit()
    db.refresh(appt)
    return _appointment_out(appt, message="Appointment rescheduled")
