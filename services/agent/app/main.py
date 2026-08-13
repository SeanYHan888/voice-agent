"""Agent service.

Three surfaces onto the same LangGraph workflow:

- `POST /chat`            — text turns, used by the Golden Dataset runner and the fallback UI
- `POST /v1/chat/completions` — the OpenAI-compatible shape ElevenLabs calls as its "custom LLM"
- `POST /calls/{id}/wrapup`  — ends a call and runs the post-call summary agent
"""
import json
import logging
import time
import uuid

import jwt
from fastapi import BackgroundTasks, Body, FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import domain_client as domain
from .config import settings
from .graph import get_graph, run_turn
from .prompts import GREETING
from .session import store
from .summarizer import summarise

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("agent")

app = FastAPI(title="agent-service")


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
def chat(body: ChatIn):
    session = store.get_or_create(body.session_id, transport=body.transport)
    if session.call_id is None:
        try:
            session.call_id = domain.start_call(session)["id"]
        except Exception:
            log.warning("Could not open call record", exc_info=True)
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
        raise HTTPException(404, "Unknown session")
    background.add_task(summarise, session)
    return {"ok": True, "call_id": session.call_id}


# --- OpenAI-compatible surface for ElevenLabs ---------------------------------


def _extract_session_id(payload: dict, header_session: str) -> str | None:
    for candidate in (
        header_session,
        payload.get("session_id"),
        payload.get("user"),
        payload.get("conversation_id"),
        (payload.get("metadata") or {}).get("session_id"),
    ):
        if candidate:
            return str(candidate)
    return None


def _last_user_message(payload: dict) -> str:
    for message in reversed(payload.get("messages", [])):
        if message.get("role") == "user":
            content = message.get("content")
            if isinstance(content, list):  # multimodal content parts
                return " ".join(part.get("text", "") for part in content if isinstance(part, dict))
            return str(content or "")
    return ""


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
    payload: dict = Body(...), x_session_id: str = Header(default="", alias="X-Session-Id")
):
    session_id = _extract_session_id(payload, x_session_id)
    session = store.get_or_create(session_id, transport="browser")
    if session.call_id is None:
        try:
            session.call_id = domain.start_call(session)["id"]
        except Exception:
            log.warning("Could not open call record", exc_info=True)

    user_text = _last_user_message(payload)
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
def models():
    """ElevenLabs probes this when validating a custom LLM endpoint."""
    return {
        "object": "list",
        "data": [{"id": settings.voice_model, "object": "model", "owned_by": "assort-dermatology"}],
    }
