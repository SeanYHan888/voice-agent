"""Call sessions.

A session holds the one fact the model is never allowed to decide for itself: which
Patient, if any, this conversation has proven to be. Tools read the patient identity
from here and mint a signed token for the domain service, so nothing the Caller says —
and nothing the model generates — can widen its own access.
"""
import time
import uuid
from dataclasses import dataclass, field

import jwt

from .config import settings

SESSION_TTL_SECONDS = 60 * 60


@dataclass
class CallSession:
    id: str
    transport: str = "browser"
    call_id: int | None = None
    patient_id: int | None = None
    patient_first_name: str | None = None
    # Number a verification code was last sent to, so confirm_verification needs no repeat.
    pending_phone: str | None = None
    # Set when this call created the patient record: they're verified, but a first visit.
    registered_this_call: bool = False
    created_at: float = field(default_factory=time.time)

    @property
    def is_verified(self) -> bool:
        return self.patient_id is not None

    def token(self) -> str:
        """Signed proof of what this session may do, for the domain service."""
        claims = {
            "sub": f"session:{self.id}",
            "role": "agent",
            "iat": int(time.time()),
            "exp": int(time.time()) + SESSION_TTL_SECONDS,
        }
        if self.call_id is not None:
            claims["call_id"] = self.call_id
        if self.patient_id is not None:
            claims["patient_id"] = self.patient_id
        return jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, CallSession] = {}

    def create(self, transport: str = "browser", patient_id: int | None = None) -> CallSession:
        session = CallSession(id=str(uuid.uuid4()), transport=transport, patient_id=patient_id)
        self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> CallSession | None:
        return self._sessions.get(session_id)

    def get_or_create(self, session_id: str | None, transport: str = "browser") -> CallSession:
        if session_id and (existing := self._sessions.get(session_id)):
            return existing
        session = self.create(transport=transport)
        if session_id:
            # Honour a client-supplied id so the voice bridge and the widget agree.
            del self._sessions[session.id]
            session.id = session_id
            self._sessions[session_id] = session
        return session

    def prune(self) -> None:
        cutoff = time.time() - SESSION_TTL_SECONDS
        for key in [k for k, s in self._sessions.items() if s.created_at < cutoff]:
            del self._sessions[key]


store = SessionStore()
