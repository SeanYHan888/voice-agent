"""Call sessions.

A session holds the one fact the model is never allowed to decide for itself: which
Patient, if any, this conversation has proven to be. Tools read the patient identity
from here and mint a signed token for the domain service, so nothing the Caller says —
and nothing the model generates — can widen its own access.

The store is in-memory; what a session has proven is also snapshotted into the
conversation's checkpoint (see graph.py) so a restart mid-call does not forget who is on
the line while still remembering what they said.
"""
import threading
import time
import uuid
from dataclasses import dataclass, field

import jwt

from .config import settings

# How long a session's signed token is good for.
SESSION_TTL_SECONDS = 60 * 60
# Silence after which a call is over: the caller hung up, closed the tab, or walked away.
# Its identity survives in the checkpoint, so a session that resumes later loses nothing.
CALL_IDLE_SECONDS = 15 * 60

# The facts worth carrying across a restart. Everything else is derivable or per-turn.
IDENTITY_FIELDS = (
    "transport",
    "call_id",
    "patient_id",
    "patient_first_name",
    "pending_phone",
    "registered_this_call",
)


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
    last_seen: float = field(default_factory=time.time)

    @property
    def is_verified(self) -> bool:
        return self.patient_id is not None

    def touch(self) -> None:
        self.last_seen = time.time()

    def snapshot(self) -> dict:
        return {name: getattr(self, name) for name in IDENTITY_FIELDS}

    def restore(self, snapshot: dict) -> None:
        for name in IDENTITY_FIELDS:
            if name in snapshot:
                setattr(self, name, snapshot[name])

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
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def create(self, transport: str = "browser", patient_id: int | None = None) -> CallSession:
        session = CallSession(id=str(uuid.uuid4()), transport=transport, patient_id=patient_id)
        with self._guard:
            self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> CallSession | None:
        return self._sessions.get(session_id)

    def get_or_create(self, session_id: str | None, transport: str = "browser") -> tuple[CallSession, bool]:
        """Return (session, created). Under the guard, so two simultaneous first turns for
        one id share a single session instead of the later one orphaning the earlier."""
        with self._guard:
            if session_id and (existing := self._sessions.get(session_id)):
                return existing, False
            session = CallSession(id=session_id or str(uuid.uuid4()), transport=transport)
            self._sessions[session.id] = session
            return session, True

    def lock_for(self, session_id: str) -> threading.Lock:
        """One lock per session: turns on the same conversation run one at a time, so a
        barge-in cannot fork the checkpoint or double-seed the transcript."""
        with self._guard:
            lock = self._locks.get(session_id)
            if lock is None:
                lock = self._locks[session_id] = threading.Lock()
            return lock

    def prune(self) -> list[CallSession]:
        """Drop sessions idle past the TTL and return them, so the caller can wrap up the
        calls that never got an explicit end (a phone hang-up, a closed tab)."""
        cutoff = time.time() - CALL_IDLE_SECONDS
        with self._guard:
            expired = [s for s in self._sessions.values() if s.last_seen < cutoff]
            for s in expired:
                del self._sessions[s.id]
                self._locks.pop(s.id, None)
        return expired


store = SessionStore()
