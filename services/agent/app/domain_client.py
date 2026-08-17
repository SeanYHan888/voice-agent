"""Thin HTTP wrapper over the domain service.

Every call carries the session's signed token, so the domain service decides what the
session may do. A refusal here is an access-control decision, not an error to work around.
"""
import httpx

from .config import settings
from .session import CallSession

TIMEOUT = httpx.Timeout(15.0, connect=5.0)


class DomainError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _request(method: str, path: str, session: CallSession | None = None, **kwargs) -> dict | list:
    headers = {"Authorization": f"Bearer {session.token()}"} if session else {}
    try:
        with httpx.Client(base_url=settings.domain_service_url, timeout=TIMEOUT) as client:
            response = client.request(method, path, headers=headers, **kwargs)
    except httpx.HTTPError as e:
        # A network failure is still an answer the tool layer must be able to phrase for
        # the caller; letting it propagate collapses the whole turn.
        raise DomainError(503, f"scheduling system unreachable ({type(e).__name__})") from e
    if response.status_code >= 400:
        detail = response.json().get("detail") if "json" in response.headers.get("content-type", "") else response.text
        if isinstance(detail, list):  # pydantic validation errors: keep the human part
            detail = "invalid input: " + "; ".join(
                f"{'.'.join(str(x) for x in err.get('loc', [])[-1:])} {err.get('msg', '')}".strip()
                for err in detail
                if isinstance(err, dict)
            )
        raise DomainError(response.status_code, str(detail))
    return response.json() if response.content else {}


def search_slots(**params) -> list[dict]:
    clean = {k: v for k, v in params.items() if v is not None}
    return _request("GET", "/slots", params=clean)


def faq_search(query: str, k: int = 3) -> list[dict]:
    return _request("POST", "/faq/search", json={"query": query, "k": k})["results"]


def request_verification(session: CallSession, phone: str) -> dict:
    return _request(
        "POST", "/verification/request", session, json={"phone": phone, "call_id": session.call_id}
    )


def confirm_verification(session: CallSession, phone: str, code: str) -> dict:
    return _request("POST", "/verification/confirm", session, json={"phone": phone, "code": code})


def register_patient(session: CallSession, **fields) -> dict:
    return _request("POST", "/patients/register", session, json=fields)


def book_appointment(session: CallSession, slot_id: int) -> dict:
    return _request("POST", "/appointments", session, json={"slot_id": slot_id})


def my_appointments(session: CallSession) -> list[dict]:
    return _request("GET", "/appointments/me", session)


def cancel_appointment(session: CallSession, appointment_id: int) -> dict:
    return _request("POST", f"/appointments/{appointment_id}/cancel", session)


def reschedule_appointment(session: CallSession, appointment_id: int, new_slot_id: int) -> dict:
    return _request(
        "POST", f"/appointments/{appointment_id}/reschedule", session, json={"new_slot_id": new_slot_id}
    )


def start_call(session: CallSession) -> dict:
    return _request(
        "POST",
        "/calls",
        session,
        json={"transport": session.transport, "patient_id": session.patient_id},
    )


def end_call(session: CallSession, transcript: str | None = None) -> dict:
    return _request("PATCH", f"/calls/{session.call_id}", session, json={"transcript": transcript})


def write_summary(session: CallSession, summary: str, intent: str, sentiment: str) -> dict:
    return _request(
        "POST",
        f"/calls/{session.call_id}/summary",
        session,
        json={"summary": summary, "intent": intent, "sentiment": sentiment},
    )


def escalate(session: CallSession, reason: str, detail: str | None = None) -> dict:
    return _request(
        "POST",
        "/escalations",
        session,
        json={"call_id": session.call_id, "reason": reason, "detail": detail},
    )
