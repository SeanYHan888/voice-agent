"""Agent service.

Three surfaces onto the same LangGraph workflow:

- `POST /chat`            — text turns, used by the Golden Dataset runner and the fallback UI
- `POST /v1/chat/completions` — the OpenAI-compatible shape ElevenLabs calls as its "custom LLM"
- `POST /calls/{id}/wrapup`  — ends a call and runs the post-call summary agent
"""
import hmac
import json
import logging
import re
import time
import uuid

import jwt
from fastapi import BackgroundTasks, Body, FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import domain_client as domain
from .config import settings
from .graph import get_graph, restore_identity, run_turn, seed_history
from .logging_middleware import RequestLogMiddleware
from .prompts import GREETING
from .session import CallSession, store
from .summarizer import summarise

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("agent")

app = FastAPI(title="agent-service", root_path="/api/agent")
app.add_middleware(RequestLogMiddleware, service="agent")


class SessionStartIn(BaseModel):
    transport: str = "browser"


class ChatIn(BaseModel):
    session_id: str | None = None
    message: str
    transport: str = "browser"


@app.get("/healthz")
def healthz():
    return {"ok": True, "service": "agent"}


@app.on_event("startup")
def warm_graph() -> None:
    try:
        get_graph()
        log.info("LangGraph workflow compiled")
    except Exception:
        log.exception("Graph compilation failed at startup")


def _patient_from_portal_token(authorization: str) -> int | None:
    """A logged-in patient arrives already identified, so their session skips Verification."""
    if not authorization.startswith("Bearer "):
        return None
    try:
        claims = jwt.decode(
            authorization.removeprefix("Bearer "),
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.InvalidTokenError:
        return None
    if claims.get("role") != "patient":
        return None
    # The portal knows the user; the domain service maps that to a patient record.
    import httpx

    try:
        response = httpx.get(
            f"{settings.domain_service_url}/patients/me",
            headers={"Authorization": authorization},
            timeout=10,
        )
        return response.json()["id"] if response.status_code == 200 else None
    except Exception:
        log.warning("Could not resolve portal patient", exc_info=True)
        return None


def _resolve_session(session_id: str | None, transport: str, background: BackgroundTasks) -> CallSession:
    """The session for this turn. A known id the store has forgotten (restart, second
    replica) is rehydrated from its checkpoint rather than started over as a stranger.
    Idle sessions are swept here too, and the calls they left open get their summary."""
    for expired in store.prune():
        if expired.call_id is not None:
            background.add_task(summarise, expired)
    session, created = store.get_or_create(session_id, transport=transport)
    if created and session_id:
        restore_identity(session)
    session.touch()
    return session


def _ensure_call(session: CallSession) -> None:
    if session.call_id is None:
        try:
            session.call_id = domain.start_call(session)["id"]
        except Exception:
            log.warning("Could not open call record", exc_info=True)


@app.post("/session")
def start_session(body: SessionStartIn, authorization: str = Header(default="")):
    """Open a call session. Called by the widget before connecting to the voice platform."""
    patient_id = _patient_from_portal_token(authorization)
    session = store.create(transport=body.transport, patient_id=patient_id)

    if patient_id is not None:
        try:
            patient = domain._request(  # noqa: SLF001 - internal call with the session's own token
                "GET", "/patients/me", session
            )
            session.patient_first_name = patient["first_name"]
        except Exception:
            log.warning("Could not load patient name", exc_info=True)

    try:
        session.call_id = domain.start_call(session)["id"]
    except Exception:
        log.exception("Could not open call record")

    greeting = GREETING
    if session.patient_first_name:
        greeting = (
            f"Thanks for calling {settings.clinic_name}, this is {settings.agent_name}. "
            f"Hi {session.patient_first_name} — how can I help you today?"
        )
    return {
        "session_id": session.id,
        "call_id": session.call_id,
        "verified": session.is_verified,
        "greeting": greeting,
    }


@app.post("/chat")
def chat(body: ChatIn, background: BackgroundTasks):
    session = _resolve_session(body.session_id, body.transport, background)
    with store.lock_for(session.id):
        _ensure_call(session)
        turn = run_turn(session, body.message)
    return {
        "session_id": session.id,
        "reply": turn["reply"],
        "tools_called": turn["tools_called"],
        "guard": turn["guard"],
        "verified": session.is_verified,
        "patient_first_name": session.patient_first_name,
    }


@app.post("/calls/{session_id}/wrapup")
def wrapup(session_id: str, background: BackgroundTasks):
    """End the call and kick off the summary agent."""
    session = store.get(session_id)
    if session is None:
        # Restarted since the call began: the checkpoint still knows the call.
        session, _ = store.get_or_create(session_id)
        if not restore_identity(session):
            store.prune()
            raise HTTPException(404, "Unknown session")
    background.add_task(summarise, session)
    return {"ok": True, "call_id": session.call_id}


# --- OpenAI-compatible surface for ElevenLabs ---------------------------------


def _require_elevenlabs_key(authorization: str) -> None:
    """Protect the public custom-LLM surface with the key configured in ElevenLabs."""
    expected = settings.elevenlabs_llm_api_key
    if not expected:
        raise HTTPException(503, "Custom LLM API key is not configured")
    if not hmac.compare_digest(authorization, f"Bearer {expected}"):
        raise HTTPException(401, "Invalid custom LLM API key")


# Markers the ElevenLabs agent's system prompt is configured to carry, e.g.
# "session_id={{session_id}}" and "conversation_id={{system__conversation_id}}". Dynamic
# variables are interpolated into that prompt before it reaches us, which makes it the one
# channel that works from the widget, the dashboard test console, and a phone call alike.
# The value must not be the next marker's keyword: with whitespace collapsed,
# "session_id= conversation_id=conv_x" would otherwise file every call under one session.
_SESSION_MARKER = re.compile(
    r"\bsession_id[ \t]*[=:][ \t]*(?!(?:session_id|conversation_id)\b)([A-Za-z0-9._:-]{8,})"
)
_CONVERSATION_MARKER = re.compile(
    r"\bconversation_id[ \t]*[=:][ \t]*(?!(?:session_id|conversation_id)\b)([A-Za-z0-9._:-]{8,})"
)


def _usable(candidate) -> str | None:
    """A candidate id, or None if it's empty or an un-substituted {{template}}."""
    if not candidate:
        return None
    text = str(candidate).strip()
    if not text or "{{" in text or text.lower() in {"none", "null", "undefined"}:
        return None
    return text


def _extract_session_id(payload: dict, header_session: str) -> str | None:
    """Work out which call session this turn belongs to.

    Ordered by specificity: an id the widget minted (which may already carry a
    portal-verified patient) beats the voice platform's own conversation id, which is
    still stable for the life of one call and is what keeps memory and verification
    intact when nothing else is passed."""
    extra = payload.get("elevenlabs_extra_body") or {}
    dynamic = extra.get("dynamic_variables") or {}
    system_text = "\n".join(
        str(m.get("content") or "")
        for m in payload.get("messages", [])
        if m.get("role") == "system"
    )
    session_marker = _SESSION_MARKER.search(system_text)
    conversation_marker = _CONVERSATION_MARKER.search(system_text)

    for candidate in (
        header_session,
        payload.get("session_id"),
        payload.get("user"),
        payload.get("user_id"),
        (payload.get("metadata") or {}).get("session_id"),
        extra.get("session_id"),
        dynamic.get("session_id"),
        session_marker.group(1) if session_marker else None,
        payload.get("conversation_id"),
        extra.get("conversation_id"),
        extra.get("system__conversation_id"),
        dynamic.get("system__conversation_id"),
        conversation_marker.group(1) if conversation_marker else None,
    ):
        if usable := _usable(candidate):
            return usable
    return None


def _message_text(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, list):  # multimodal content parts
        return " ".join(part.get("text", "") for part in content if isinstance(part, dict))
    return str(content or "")


def _last_user_message(payload: dict) -> str:
    """The caller's utterance for this turn — only if the transcript ends with one. A
    request that ends with an assistant message (turn timeout, resend after a barge-in)
    must not replay the previous utterance and re-run its tool calls."""
    messages = payload.get("messages", [])
    if messages and messages[-1].get("role") == "user":
        return _message_text(messages[-1])
    return ""


def _prior_turns(payload: dict) -> list:
    """Everything the platform remembers before this turn's user message, as graph
    messages. Its own system prompt is dropped — ours is applied inside the graph."""
    from langchain_core.messages import AIMessage, HumanMessage

    messages = [m for m in payload.get("messages", []) if m.get("role") in ("user", "assistant")]
    if messages and messages[-1].get("role") == "user":
        messages = messages[:-1]
    prior = []
    for m in messages:
        text = _message_text(m).strip()
        if not text:
            continue
        prior.append(HumanMessage(content=text) if m["role"] == "user" else AIMessage(content=text))
    return prior


def _completion_payload(model: str, content: str) -> dict:
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def _stream_chunks(model: str, content: str):
    """Emit the reply as a single SSE delta. The LangGraph turn is already complete by
    the time we get here — chunking it further would not reach the caller any sooner."""
    created = int(time.time())
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"

    def frame(delta: dict, finish: str | None = None) -> str:
        return "data: " + json.dumps(
            {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
            }
        ) + "\n\n"

    yield frame({"role": "assistant", "content": content})
    yield frame({}, "stop")
    yield "data: [DONE]\n\n"


@app.post("/v1/chat/completions")
def chat_completions(
    background: BackgroundTasks,
    payload: dict = Body(...),
    x_session_id: str = Header(default="", alias="X-Session-Id"),
    authorization: str = Header(default=""),
):
    _require_elevenlabs_key(authorization)
    session_id = _extract_session_id(payload, x_session_id)
    if session_id is None:
        # Without an id every turn is a stranger: no memory, and verification cannot
        # survive to the next turn. The transcript backfill below keeps the conversation
        # coherent, but the fix is in the ElevenLabs agent config — see docs/elevenlabs-setup.md.
        log.warning(
            "Voice turn arrived without any session or conversation id; "
            "memory and verification will not persist across turns"
        )
    # A session the widget already opened keeps its transport; a call that reaches us only
    # through the voice platform is a phone-style call.
    session = _resolve_session(session_id, "phone", background)
    user_text = _last_user_message(payload)
    with store.lock_for(session.id):
        _ensure_call(session)
        prior = _prior_turns(payload)
        if prior:
            try:
                seed_history(session, prior)
            except Exception:
                log.warning("Could not seed history from platform transcript", exc_info=True)
        reply = run_turn(session, user_text)["reply"] if user_text.strip() else GREETING
    model = payload.get("model") or settings.voice_model

    if payload.get("stream"):
        return StreamingResponse(_stream_chunks(model, reply), media_type="text/event-stream")
    return _completion_payload(model, reply)


class AnalyticsIn(BaseModel):
    question: str


@app.post("/analytics")
def analytics(body: AnalyticsIn, authorization: str = Header(default="")):
    """Admin-only. The caller's own token is forwarded, so the domain service — not this
    service — decides whether the query may run at all."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing bearer token")
    token = authorization.removeprefix("Bearer ")
    try:
        claims = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token")
    if claims.get("role") != "admin":
        raise HTTPException(403, "Admin role required")

    from .analytics import ask

    return ask(body.question, token)


@app.get("/v1/models")
def models(authorization: str = Header(default="")):
    """ElevenLabs probes this when validating a custom LLM endpoint."""
    _require_elevenlabs_key(authorization)
    return {
        "object": "list",
        "data": [{"id": settings.voice_model, "object": "model", "owned_by": "assort-dermatology"}],
    }
