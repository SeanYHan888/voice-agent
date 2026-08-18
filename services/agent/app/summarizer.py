"""Post-call pipeline: a second, slower agent that reads a finished Call and writes its
summary, intent, and sentiment. Runs on the analysis model since nobody is waiting on it."""
import json
import logging

from langchain_core.messages import AIMessage, HumanMessage
from langchain_openai import ChatOpenAI

from . import domain_client as domain
from .config import settings
from .graph import _langfuse_handler, transcript_of
from .prompts import SUMMARY_PROMPT
from .session import CallSession

log = logging.getLogger(__name__)

VALID_INTENTS = {
    "booking",
    "reschedule",
    "cancellation",
    "clinic_info",
    "medical_question",
    "complaint",
    "other",
}
VALID_SENTIMENTS = {"positive", "neutral", "negative"}


def render_transcript(session: CallSession) -> str:
    lines = []
    for message in transcript_of(session):
        if isinstance(message, HumanMessage):
            lines.append(f"Caller: {message.content}")
        elif isinstance(message, AIMessage) and isinstance(message.content, str) and message.content.strip():
            lines.append(f"Maya: {message.content}")
    return "\n".join(lines)


def summarise(session: CallSession) -> dict | None:
    """Write the Call Summary. Returns None when there is nothing worth summarising."""
    if session.call_id is None:
        return None  # nothing was ever recorded for this session
    transcript = render_transcript(session)
    try:
        domain.end_call(session, transcript or None)
    except Exception:
        log.warning("Could not store transcript for call %s", session.call_id, exc_info=True)
    if not transcript.strip():
        return None  # closed, but nothing worth summarising

    llm = ChatOpenAI(
        model=settings.analysis_model,
        api_key=settings.openai_api_key,
        timeout=60,
        max_retries=2,
    )
    config = {
        "metadata": {
            "langfuse_session_id": session.id,
            **({"langfuse_user_id": f"patient:{session.patient_id}"} if session.is_verified else {}),
            "call_id": session.call_id,
        },
        "tags": ["maya", "post-call-summary"],
    }
    if _langfuse_handler is not None:
        config["callbacks"] = [_langfuse_handler]

    try:
        raw = llm.invoke(SUMMARY_PROMPT.format(transcript=transcript), config=config).content
        parsed = json.loads(str(raw).strip().removeprefix("```json").removeprefix("```").removesuffix("```"))
        if not isinstance(parsed, dict):
            raise ValueError(f"summary model returned {type(parsed).__name__}, not an object")
    except Exception:
        log.exception("Summary generation failed for call %s", session.call_id)
        return None

    result = {
        "summary": str(parsed.get("summary", ""))[:1000],
        "intent": parsed.get("intent") if parsed.get("intent") in VALID_INTENTS else "other",
        "sentiment": parsed.get("sentiment") if parsed.get("sentiment") in VALID_SENTIMENTS else "neutral",
    }

    try:
        domain.write_summary(session, **result)
    except Exception:
        log.exception("Could not store summary for call %s", session.call_id)
        return None
    return result
