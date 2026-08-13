from datetime import date, datetime

from pydantic import BaseModel, Field


class ProviderOut(BaseModel):
    id: int
    name: str
    title: str

    model_config = {"from_attributes": True}


class SlotOut(BaseModel):
    id: int
    provider_id: int
    provider_name: str
    visit_type: str
    starts_at: datetime


class PatientOut(BaseModel):
    id: int
    first_name: str
    last_name: str
    dob: date
    phone: str
    user_id: int | None = None

    model_config = {"from_attributes": True}


class ClaimIn(BaseModel):
    phone: str
    dob: date


class BookIn(BaseModel):
    slot_id: int
    patient_id: int | None = None  # admin-only: book on behalf of a patient


class RescheduleIn(BaseModel):
    new_slot_id: int


class AppointmentOut(BaseModel):
    id: int
    patient_id: int
    status: str
    provider_name: str
    visit_type: str
    starts_at: datetime
    requires_approval: bool = False
    message: str | None = None


class CallIn(BaseModel):
    transport: str = "browser"
    caller_phone: str | None = None
    patient_id: int | None = None


class CallEndIn(BaseModel):
    transcript: str | None = None


class CallSummaryIn(BaseModel):
    summary: str
    intent: str
    sentiment: str


class CallOut(BaseModel):
    id: int
    transport: str
    started_at: datetime
    ended_at: datetime | None
    patient_id: int | None
    summary: str | None = None
    intent: str | None = None
    sentiment: str | None = None
    has_feedback: bool = False


class FeedbackIn(BaseModel):
    call_id: int
    stars: int = Field(ge=1, le=5)
    comment: str | None = None


class VerificationRequestIn(BaseModel):
    phone: str
    call_id: int | None = None


class VerificationConfirmIn(BaseModel):
    phone: str
    code: str


class VerificationRequestOut(BaseModel):
    sent: bool
    masked_phone: str | None = None
    message: str


class VerificationConfirmOut(BaseModel):
    verified: bool
    patient_id: int | None = None
    first_name: str | None = None
    message: str


class RegisterPatientIn(BaseModel):
    first_name: str
    last_name: str
    dob: date
    phone: str


class EscalationIn(BaseModel):
    call_id: int | None = None
    reason: str
    detail: str | None = None


class AdminTaskOut(BaseModel):
    id: int
    kind: str
    status: str
    payload: dict
    call_id: int | None
    created_at: datetime
    resolved_at: datetime | None
