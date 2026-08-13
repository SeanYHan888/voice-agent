import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import Principal, require_admin
from ..db import get_db
from ..models import AdminTask, Appointment, Call, CallSummary, Feedback, Patient, Slot
from ..schemas import AdminTaskOut, PatientOut

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/patients", response_model=list[PatientOut])
def patients(
    phone: str | None = None,
    _: Principal = Depends(require_admin),
    db: Session = Depends(get_db),
):
    q = select(Patient).order_by(Patient.id)
    if phone:
        q = q.where(Patient.phone == phone)
    return db.scalars(q).all()


@router.get("/tasks", response_model=list[AdminTaskOut])
def tasks(
    status: str | None = "open",
    kind: str | None = None,
    _: Principal = Depends(require_admin),
    db: Session = Depends(get_db),
):
    q = select(AdminTask).order_by(AdminTask.created_at.desc())
    if status:
        q = q.where(AdminTask.status == status)
    if kind:
        q = q.where(AdminTask.kind == kind)
    return [
        AdminTaskOut(
            id=t.id,
            kind=t.kind,
            status=t.status,
            payload=json.loads(t.payload),
            call_id=t.call_id,
            created_at=t.created_at,
            resolved_at=t.resolved_at,
        )
        for t in db.scalars(q).all()
    ]


@router.post("/tasks/{task_id}/approve")
def approve(
    task_id: int,
    _: Principal = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Execute the change the agent held back. The requested slot is validated now,
    not when the request was made, so a slot taken in the meantime fails cleanly."""
    task = db.get(AdminTask, task_id)
    if task is None:
        raise HTTPException(404, "Unknown task")
    if task.status != "open":
        raise HTTPException(409, f"Task already {task.status}")

    payload = json.loads(task.payload)
    if task.kind == "escalation":
        task.status = "done"
        task.resolved_at = datetime.now(timezone.utc)
        db.commit()
        return {"ok": True, "message": "Escalation closed"}

    appt = db.get(Appointment, payload["appointment_id"])
    if appt is None:
        raise HTTPException(404, "Appointment no longer exists")

    if payload["action"] == "cancel":
        appt.status = "cancelled"
        appt.slot.status = "open"
        message = "Cancellation approved"
    elif payload["action"] == "reschedule":
        new_slot = db.scalars(
            select(Slot).where(Slot.id == payload["new_slot_id"]).with_for_update()
        ).one_or_none()
        if new_slot is None or new_slot.status != "open":
            raise HTTPException(409, "The requested time is no longer available")
        appt.slot.status = "open"
        new_slot.status = "booked"
        appt.slot_id = new_slot.id
        appt.status = "booked"
        message = "Reschedule approved"
    else:
        raise HTTPException(400, f"Unknown action {payload['action']}")

    if appt.status == "pending_change" and payload["action"] == "cancel":
        appt.status = "cancelled"
    task.status = "approved"
    task.resolved_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True, "message": message}


@router.post("/tasks/{task_id}/reject")
def reject(
    task_id: int,
    _: Principal = Depends(require_admin),
    db: Session = Depends(get_db),
):
    task = db.get(AdminTask, task_id)
    if task is None:
        raise HTTPException(404, "Unknown task")
    if task.status != "open":
        raise HTTPException(409, f"Task already {task.status}")

    payload = json.loads(task.payload)
    if task.kind == "approval":
        appt = db.get(Appointment, payload["appointment_id"])
        if appt is not None and appt.status == "pending_change":
            appt.status = "booked"  # the original appointment stands
    task.status = "rejected"
    task.resolved_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True, "message": "Request rejected; original appointment stands"}


@router.get("/stats")
def stats(_: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    since = datetime.now(timezone.utc) - timedelta(days=14)

    calls_per_day = [
        {"day": str(day), "calls": count}
        for day, count in db.execute(
            select(func.date(Call.started_at), func.count())
            .where(Call.started_at >= since)
            .group_by(func.date(Call.started_at))
            .order_by(func.date(Call.started_at))
        ).all()
    ]

    total_calls = db.scalar(select(func.count()).select_from(Call)) or 0
    calls_with_booking = (
        db.scalar(
            select(func.count(func.distinct(Appointment.call_id))).where(
                Appointment.call_id.is_not(None)
            )
        )
        or 0
    )

    intents = [
        {"intent": intent, "count": count}
        for intent, count in db.execute(
            select(CallSummary.intent, func.count()).group_by(CallSummary.intent)
        ).all()
    ]
    sentiments = [
        {"sentiment": sentiment, "count": count}
        for sentiment, count in db.execute(
            select(CallSummary.sentiment, func.count()).group_by(CallSummary.sentiment)
        ).all()
    ]

    return {
        "calls_per_day": calls_per_day,
        "total_calls": total_calls,
        "booking_conversion": round(calls_with_booking / total_calls, 3) if total_calls else 0.0,
        "avg_feedback": round(db.scalar(select(func.avg(Feedback.stars))) or 0, 2),
        "feedback_count": db.scalar(select(func.count()).select_from(Feedback)) or 0,
        "appointments_booked": db.scalar(
            select(func.count()).select_from(Appointment).where(Appointment.status == "booked")
        )
        or 0,
        "open_tasks": db.scalar(
            select(func.count()).select_from(AdminTask).where(AdminTask.status == "open")
        )
        or 0,
        "patients": db.scalar(select(func.count()).select_from(Patient)) or 0,
        "intents": intents,
        "sentiments": sentiments,
    }
