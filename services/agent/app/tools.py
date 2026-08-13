"""Maya's tools.

Note what these signatures do *not* accept: a patient id. Identity comes from the call
session, which only Verification can set, so a Caller who talks their way past the prompt
still cannot reach another patient's records. Tool errors are returned as text rather
than raised, so the model can apologise and recover instead of the turn collapsing.
"""
import contextvars
import logging
from datetime import datetime

from langchain_core.tools import tool

from . import domain_client as domain
from .domain_client import DomainError
from .guardrails import sanitise_retrieved
from .session import CallSession

log = logging.getLogger(__name__)

_current_session: contextvars.ContextVar[CallSession] = contextvars.ContextVar("call_session")

VERIFY_FIRST = (
    "This caller hasn't been verified yet. Ask for the phone number on their file and "
    "call start_verification, then finish_verification with the code they read back."
)


def set_session(session: CallSession) -> contextvars.Token:
    return _current_session.set(session)


def reset_session(token: contextvars.Token) -> None:
    _current_session.reset(token)


def session() -> CallSession:
    return _current_session.get()


def _speakable(moment: datetime) -> str:
    return moment.strftime("%A %B %-d at %-I:%M %p")


@tool
def find_appointment_times(
    visit_type: str = "New Patient",
    day: str | None = None,
    provider_name: str | None = None,
) -> str:
    """Find open appointment times. visit_type is "New Patient" (30 min, first visit) or
    "Follow-up" (15 min, existing patients). day is an optional YYYY-MM-DD date."""
    try:
        slots = domain.search_slots(visit_type=visit_type, on=day, limit=60)
    except DomainError as e:
        return f"Couldn't reach the schedule ({e.message}). Offer to try again in a moment."

    if provider_name:
        wanted = provider_name.lower().replace("dr.", "").strip()
        slots = [s for s in slots if wanted in s["provider_name"].lower()] or slots

    if not slots:
        return "No open times matched. Suggest a different day or visit type."

    lines = []
    for slot in slots[:6]:
        starts = datetime.fromisoformat(slot["starts_at"])
        lines.append(
            f"slot_id={slot['id']} | {_speakable(starts)} | {slot['provider_name']} | {slot['visit_type']}"
        )
    return "Open times:\n" + "\n".join(lines) + "\nOffer two or three of these out loud, not all of them."


@tool
def start_verification(phone: str) -> str:
    """Send a one-time code to the phone number on the patient's file. Use this before
    any action on a patient's records. phone should be digits, e.g. 5550100101."""
    current = session()
    digits = "".join(c for c in phone if c.isdigit())
    if len(digits) == 10:
        digits = f"1{digits}"
    normalised = f"+{digits}"

    try:
        result = domain.request_verification(current, normalised)
    except DomainError as e:
        return f"Verification service problem: {e.message}"

    if not result["sent"]:
        return (
            "No patient record has that number. Offer to register them as a new patient "
            "(you'll need first name, last name, and date of birth)."
        )
    current.pending_phone = normalised
    return f"Code sent to {result['masked_phone']}. Ask the caller to read back the six digits."


@tool
def finish_verification(code: str) -> str:
    """Check the six-digit code the caller read back, which identifies them as the patient."""
    current = session()
    if not current.pending_phone:
        return "No code has been sent yet — call start_verification first."

    try:
        result = domain.confirm_verification(current, current.pending_phone, code)
    except DomainError as e:
        return f"Verification service problem: {e.message}"

    if not result["verified"]:
        return f"Not verified: {result['message']}. Offer to resend the code."

    current.patient_id = result["patient_id"]
    current.patient_first_name = result["first_name"]
    return f"Verified — this caller is {result['first_name']}. You may now act on their records."


@tool
def register_new_patient(first_name: str, last_name: str, date_of_birth: str, phone: str) -> str:
    """Create a record for a first-time caller. date_of_birth must be YYYY-MM-DD."""
    current = session()
    digits = "".join(c for c in phone if c.isdigit())
    if len(digits) == 10:
        digits = f"1{digits}"

    try:
        patient = domain.register_patient(
            current,
            first_name=first_name,
            last_name=last_name,
            dob=date_of_birth,
            phone=f"+{digits}",
        )
    except DomainError as e:
        if e.status == 409:
            return "That number already has a record — use start_verification instead."
        return f"Couldn't create the record: {e.message}"

    current.patient_id = patient["id"]
    current.patient_first_name = patient["first_name"]
    return f"Registered {patient['first_name']} and verified this session. You may now book."


@tool
def book_appointment(slot_id: int) -> str:
    """Book one of the open times returned by find_appointment_times."""
    current = session()
    if not current.is_verified:
        return VERIFY_FIRST
    try:
        appointment = domain.book_appointment(current, slot_id)
    except DomainError as e:
        if e.status == 409:
            return f"{e.message}. Search again and offer a different time."
        if e.status == 403:
            return VERIFY_FIRST
        return f"Booking failed: {e.message}"
    starts = datetime.fromisoformat(appointment["starts_at"])
    return (
        f"Booked: {appointment['visit_type']} with {appointment['provider_name']} on "
        f"{_speakable(starts)} (appointment_id={appointment['id']}). Confirm it back to the caller."
    )


@tool
def list_my_appointments() -> str:
    """List the verified caller's upcoming appointments."""
    current = session()
    if not current.is_verified:
        return VERIFY_FIRST
    try:
        appointments = domain.my_appointments(current)
    except DomainError as e:
        return f"Couldn't read the schedule: {e.message}"
    if not appointments:
        return "No upcoming appointments on file."
    return "\n".join(
        f"appointment_id={a['id']} | {_speakable(datetime.fromisoformat(a['starts_at']))} | "
        f"{a['provider_name']} | {a['visit_type']} | {a['status']}"
        for a in appointments
    )


@tool
def cancel_appointment(appointment_id: int) -> str:
    """Cancel an upcoming appointment belonging to the verified caller."""
    current = session()
    if not current.is_verified:
        return VERIFY_FIRST
    try:
        result = domain.cancel_appointment(current, appointment_id)
    except DomainError as e:
        if e.status == 403:
            return "That appointment doesn't belong to this caller. Do not discuss its details."
        return f"Couldn't cancel: {e.message}"
    if result["requires_approval"]:
        return (
            "Held for staff review — it's within 24 hours of the visit. Tell the caller a staff "
            "member will confirm shortly, and that the appointment stands until then."
        )
    return "Cancelled. Confirm it back to the caller."


@tool
def reschedule_appointment(appointment_id: int, new_slot_id: int) -> str:
    """Move an appointment to a different open slot."""
    current = session()
    if not current.is_verified:
        return VERIFY_FIRST
    try:
        result = domain.reschedule_appointment(current, appointment_id, new_slot_id)
    except DomainError as e:
        if e.status == 403:
            return "That appointment doesn't belong to this caller. Do not discuss its details."
        if e.status == 409:
            return f"{e.message}. Offer a different time."
        return f"Couldn't reschedule: {e.message}"
    if result["requires_approval"]:
        return (
            "Held for staff review — it's within 24 hours of the visit. Tell the caller a staff "
            "member will confirm shortly."
        )
    starts = datetime.fromisoformat(result["starts_at"])
    return f"Moved to {_speakable(starts)}. Confirm it back to the caller."


@tool
def lookup_clinic_info(question: str) -> str:
    """Answer questions about the clinic: hours, location, parking, what to bring,
    policies, visit preparation. Use this rather than answering from memory."""
    try:
        results = domain.faq_search(question, k=3)
    except DomainError as e:
        return f"Couldn't reach the clinic information: {e.message}"
    if not results:
        return (
            "Nothing in the clinic information covers that. Tell the caller you don't have "
            "that information rather than guessing, and offer to take a message for the staff."
        )
    return "\n\n".join(f"{r['title']}: {sanitise_retrieved(r['text'])}" for r in results)


@tool
def transfer_to_staff(reason: str, detail: str | None = None) -> str:
    """Hand the caller to a human. Use for medical questions, complaints, anything you
    cannot do, or when the caller asks for a person. reason is a short slug such as
    medical_question, complaint, billing, or caller_request."""
    current = session()
    try:
        domain.escalate(current, reason, detail)
    except DomainError as e:
        log.warning("Escalation failed: %s", e.message)
        return "Tell the caller you'll have someone follow up, and take no further action."
    return "A staff member has been notified. Tell the caller someone will follow up shortly."


ALL_TOOLS = [
    find_appointment_times,
    start_verification,
    finish_verification,
    register_new_patient,
    book_appointment,
    list_my_appointments,
    cancel_appointment,
    reschedule_appointment,
    lookup_clinic_info,
    transfer_to_staff,
]
