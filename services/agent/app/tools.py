"""Maya's tools.

Note what these signatures do *not* accept: a patient id. Identity comes from the call
session, which only Verification can set, so a Caller who talks their way past the prompt
still cannot reach another patient's records. Tool errors are returned as text rather
than raised, so the model can apologise and recover instead of the turn collapsing.
"""
import contextvars
import logging
import re
from datetime import date, datetime

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


# What the caller hears for an appointment's status; the raw value is a database enum.
_STATUS_WORDS = {
    "booked": "booked",
    "pending_change": "awaiting staff review",
    "cancelled": "cancelled",
}


def _speakable(moment: datetime) -> str:
    return moment.strftime("%A %B %-d at %-I:%M %p")


_VISIT_TYPES = {"followup": "Follow-up", "newpatient": "New Patient"}


def _visit_type(raw: str | None) -> str | None:
    """"follow up", "FOLLOW-UP", "new patient" → the exact names the domain filters on."""
    if not raw:
        return None
    return _VISIT_TYPES.get(re.sub(r"[^a-z]", "", raw.lower()), raw)


def _iso_date(raw: str | None) -> str | None:
    """A YYYY-MM-DD string, or None if it isn't one. The model must resolve "tomorrow"
    itself (today's date is in the prompt); the domain returns a 422 for anything else."""
    if not raw:
        return None
    try:
        return date.fromisoformat(raw.strip()).isoformat()
    except ValueError:
        return None


def _e164(raw: str) -> str | None:
    """+1XXXXXXXXXX from however the number was spoken, or None if it isn't a full
    ten-digit North American number. Same rule as the domain's normalize_phone."""
    digits = "".join(c for c in raw if c.isdigit())
    if len(digits) == 10:
        digits = f"1{digits}"
    if len(digits) != 11 or not digits.startswith("1"):
        return None
    return f"+{digits}"


PHONE_PROBLEM = (
    "That isn't a full ten-digit phone number. Ask the caller for the whole number, "
    "area code first."
)


@tool
def list_providers() -> str:
    """The clinic's doctors, with what each one does. Use this when a caller asks who
    the doctors are, wants a particular kind of specialist, or wants to switch to a
    different doctor — never name providers from memory."""
    try:
        providers = domain.providers()
    except DomainError as e:
        return f"Couldn't reach the provider list ({e.message}). Offer to try again in a moment."
    if not providers:
        return "No providers are listed."
    return "Our providers:\n" + "\n".join(f"{p['name']} — {p['title']}" for p in providers) + (
        "\nTo book or move a visit with one of them, call find_appointment_times with "
        "provider_name set to that name."
    )


@tool
def find_appointment_times(
    visit_type: str | None = None,
    day: str | None = None,
    provider_name: str | None = None,
) -> str:
    """Find open appointment times. visit_type is "New Patient" (30 min, first visit) or
    "Follow-up" (15 min, returning patients). Leave it out and it follows from who is on
    the line: a verified patient gets Follow-up times, anyone else New Patient times.
    day is an optional YYYY-MM-DD date."""
    visit_type = _visit_type(visit_type)
    if not visit_type:
        current = session()
        returning = current.is_verified and not current.registered_this_call
        visit_type = "Follow-up" if returning else "New Patient"
    if day and not (day := _iso_date(day)):
        return "day must be a YYYY-MM-DD date — work it out from today's date in your instructions and call again."
    try:
        slots = domain.search_slots(visit_type=visit_type, on=day, limit=60)
    except DomainError as e:
        return f"Couldn't reach the schedule ({e.message}). Offer to try again in a moment."

    preface = ""
    if provider_name:
        wanted = re.sub(r"^(dr\.?|doctor)\s*", "", provider_name.lower().strip()).strip()
        with_provider = [s for s in slots if wanted in s["provider_name"].lower()]
        if with_provider:
            slots = with_provider
        elif slots:
            # Don't silently widen: the caller asked for someone specific, and Maya must
            # say so before offering another doctor's times.
            preface = (
                f"No open {visit_type} times with {provider_name} on that day. Tell the "
                "caller so, then offer these with other providers if they'd like:\n"
            )

    if not slots:
        return "No open times matched. Suggest a different day or visit type."

    lines = []
    for slot in slots[:6]:
        starts = datetime.fromisoformat(slot["starts_at"])
        lines.append(
            f"slot_id={slot['id']} | {_speakable(starts)} | {slot['provider_name']} | {slot['visit_type']}"
        )
    return preface + "Open times:\n" + "\n".join(lines) + "\nOffer two or three of these out loud, not all of them."


@tool
def start_verification(phone: str) -> str:
    """Send a one-time code to the phone number on the patient's file. Use this before
    any action on a patient's records. phone should be digits, e.g. 5550100101."""
    current = session()
    normalised = _e164(phone)
    if normalised is None:
        return PHONE_PROBLEM

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

    # Speech-to-text renders a read-back code as "1 2 3 4 5 6" or "123-456" as often as
    # "123456"; the code is the digits, whatever came between them.
    digits = "".join(c for c in code if c.isdigit())
    if len(digits) != 6:
        return (
            f"That doesn't look like a six-digit code (heard {code!r}). Ask the caller to "
            "read the six digits again, one at a time."
        )

    try:
        result = domain.confirm_verification(current, current.pending_phone, digits)
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
    normalised = _e164(phone)
    if normalised is None:
        return PHONE_PROBLEM
    dob = _iso_date(date_of_birth)
    if dob is None:
        return "date_of_birth must be YYYY-MM-DD. Confirm the caller's date of birth and call again."

    try:
        patient = domain.register_patient(
            current,
            first_name=first_name,
            last_name=last_name,
            dob=dob,
            phone=normalised,
        )
    except DomainError as e:
        if e.status == 409:
            return "That number already has a record — use start_verification instead."
        return f"Couldn't create the record: {e.message}"

    current.patient_id = patient["id"]
    current.patient_first_name = patient["first_name"]
    current.registered_this_call = True
    return (
        f"Registered {patient['first_name']} and verified this session. Tell them their record "
        "is set up, then find New Patient times."
    )


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
    appointments = [a for a in appointments if a["status"] != "cancelled"]
    if not appointments:
        return "No upcoming appointments on file."
    return "\n".join(
        f"appointment_id={a['id']} | {_speakable(datetime.fromisoformat(a['starts_at']))} | "
        f"{a['provider_name']} | {a['visit_type']} | {_STATUS_WORDS.get(a['status'], a['status'])}"
        for a in appointments
    )


def _state_conflict(message: str) -> str:
    """The domain refused because of the appointment's state, not the slot."""
    if "pending_change" in message:
        return (
            "That appointment is already awaiting staff review for an earlier change. Don't "
            "request another — tell the caller staff will confirm, and check "
            "list_my_appointments if they ask again."
        )
    if "cancelled" in message:
        return "That appointment was already cancelled. Offer to book a new one."
    return f"Couldn't change it: {message}"


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
        if e.status == 409:
            return _state_conflict(e.message)
        return f"Couldn't cancel: {e.message}"
    if result["requires_approval"]:
        return (
            "Held for staff review — it's within 24 hours of the visit. Tell the caller a staff "
            "member will confirm shortly, and that the appointment stands until then. If they "
            "ask about it again later in the call, check list_my_appointments rather than "
            "repeating this — staff may already have acted."
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
            if "taken" in e.message.lower():
                return f"{e.message}. Offer a different time."
            return _state_conflict(e.message)
        return f"Couldn't reschedule: {e.message}"
    if result["requires_approval"]:
        return (
            "Held for staff review — it's within 24 hours of the visit. Tell the caller a staff "
            "member will confirm shortly. If they ask about it again later in the call, check "
            "list_my_appointments rather than repeating this — 'booked' at the new time means "
            "staff approved it."
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
    list_providers,
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
