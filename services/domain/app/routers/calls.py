import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import Principal, get_principal, owns_or_admin, require_patient_identity
from ..db import get_db
from ..models import AdminTask, Call, CallSummary, Feedback
from ..schemas import (
    CallEndIn,
    CallIn,
    CallOut,
    CallSummaryIn,
    EscalationIn,
    FeedbackIn,
)

router = APIRouter(tags=["calls"])


def _require_agent(principal: Principal) -> None:
    if principal.role not in ("agent", "admin"):
        raise HTTPException(403, "Only the voice agent records calls")


def _call_out(call: Call, summary: CallSummary | None, has_feedback: bool) -> CallOut:
    return CallOut(
        id=call.id,
        transport=call.transport,
        started_at=call.started_at,
        ended_at=call.ended_at,
        patient_id=call.patient_id,
        summary=summary.summary if summary else None,
        intent=summary.intent if summary else None,
        sentiment=summary.sentiment if summary else None,
        has_feedback=has_feedback,
    )


@router.post("/calls", status_code=201)
def start_call(
    body: CallIn,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    _require_agent(principal)
    call = Call(
        transport=body.transport,
        caller_phone=body.caller_phone,
        patient_id=body.patient_id,
    )
    db.add(call)
    db.commit()
    db.refresh(call)
    return {"id": call.id, "started_at": call.started_at}


@router.patch("/calls/{call_id}")
def end_call(
    call_id: int,
    body: CallEndIn,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    _require_agent(principal)
    call = db.get(Call, call_id)
    if call is None:
        raise HTTPException(404, "Unknown call")
    call.ended_at = datetime.now(timezone.utc)
    if body.transcript is not None:
        call.transcript = body.transcript
    # A session that verified mid-conversation belongs to that patient.
    if call.patient_id is None and principal.patient_id is not None:
        call.patient_id = principal.patient_id
    db.commit()
    return {"ok": True, "ended_at": call.ended_at}


@router.post("/calls/{call_id}/summary", status_code=201)
def write_summary(
    call_id: int,
    body: CallSummaryIn,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    _require_agent(principal)
    if db.get(Call, call_id) is None:
        raise HTTPException(404, "Unknown call")
    existing = db.scalar(select(CallSummary).where(CallSummary.call_id == call_id))
    if existing is not None:
        existing.summary, existing.intent, existing.sentiment = (
            body.summary,
            body.intent,
            body.sentiment,
        )
    else:
        db.add(
            CallSummary(
                call_id=call_id,
                summary=body.summary,
                intent=body.intent,
                sentiment=body.sentiment,
            )
        )
    db.commit()
    return {"ok": True}


@router.get("/calls/me", response_model=list[CallOut])
def my_calls(
    principal: Principal = Depends(require_patient_identity),
    db: Session = Depends(get_db),
):
    calls = db.scalars(
        select(Call)
        .where(Call.patient_id == principal.patient_id)
        .order_by(Call.started_at.desc())
    ).all()
    out = []
    for call in calls:
        summary = db.scalar(select(CallSummary).where(CallSummary.call_id == call.id))
        has_feedback = db.scalar(select(Feedback).where(Feedback.call_id == call.id)) is not None
        out.append(_call_out(call, summary, has_feedback))
    return out


@router.post("/feedback", status_code=201)
def leave_feedback(
    body: FeedbackIn,
    principal: Principal = Depends(require_patient_identity),
    db: Session = Depends(get_db),
):
    call = db.get(Call, body.call_id)
    if call is None:
        raise HTTPException(404, "Unknown call")
    if call.patient_id is None:
        raise HTTPException(403, "That call has no patient on record")
    owns_or_admin(principal, call.patient_id)
    if db.scalar(select(Feedback).where(Feedback.call_id == call.id)) is not None:
        raise HTTPException(409, "Feedback already left for this call")
    db.add(
        Feedback(
            call_id=call.id,
            patient_id=call.patient_id,
            stars=body.stars,
            comment=body.comment,
        )
    )
    db.commit()
    return {"ok": True}


@router.post("/escalations", status_code=201)
def escalate(
    body: EscalationIn,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    _require_agent(principal)
    task = AdminTask(
        kind="escalation",
        payload=json.dumps(
            {
                "reason": body.reason,
                "detail": body.detail,
                "patient_id": principal.patient_id,
            }
        ),
        call_id=body.call_id or principal.call_id,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return {"id": task.id, "message": "A staff member will follow up"}
