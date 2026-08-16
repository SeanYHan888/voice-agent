"""Maya's LangGraph workflow.

    START → input_guard ─(blocked)────────────────→ END
                │
              (ok)
                ↓
            reason ⇄ tools          (loops while the model calls tools)
                │
                ↓
           output_guard → END

The guards sit outside the model on both sides, so a blocked turn never reaches the LLM
and a bad reply never reaches the caller's ears. Conversation history lives in a Postgres
checkpoint keyed by the call session, not in whatever the voice platform sends us.
"""
import logging
import os
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from . import domain_client as domain
from .config import settings
from .guardrails import check_input, check_output
from .prompts import system_prompt
from .session import CallSession
from .tools import ALL_TOOLS, reset_session, set_session

log = logging.getLogger(__name__)

for key, value in {
    "LANGFUSE_PUBLIC_KEY": settings.langfuse_public_key,
    "LANGFUSE_SECRET_KEY": settings.langfuse_secret_key,
    "LANGFUSE_HOST": settings.langfuse_host,
}.items():
    if value:
        os.environ.setdefault(key, value)

try:
    from langfuse.langchain import CallbackHandler

    _langfuse_handler = CallbackHandler() if settings.langfuse_public_key else None
except Exception:
    log.exception("LangFuse callback handler unavailable; traces will not be sent")
    _langfuse_handler = None


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    guard: str | None


_reasoning_effort: str | None = settings.voice_reasoning_effort or None


def _build_llm() -> ChatOpenAI:
    kwargs = {
        "model": settings.voice_model,
        "api_key": settings.openai_api_key,
        "timeout": 30,
        "max_retries": 2,
    }
    if _reasoning_effort:
        kwargs["reasoning_effort"] = _reasoning_effort
    return ChatOpenAI(**kwargs).bind_tools(ALL_TOOLS)


# Constructed on first use, not at import: the client raises without an API key, and a
# missing key should degrade conversations, not stop the service from booting.
_llm: object | None = None


def _get_llm():
    global _llm
    if _llm is None:
        _llm = _build_llm()
    return _llm


def input_guard(state: AgentState) -> dict:
    last = state["messages"][-1]
    if not isinstance(last, HumanMessage):
        return {"guard": None}

    verdict = check_input(str(last.content))
    if not verdict.triggered:
        return {"guard": None}

    log.info("Input guard tripped: %s", verdict.kind)
    if verdict.escalate_reason:
        try:
            from .tools import session as current_session

            domain.escalate(current_session(), verdict.escalate_reason, str(last.content)[:500])
        except Exception:
            log.warning("Could not record escalation for %s", verdict.kind, exc_info=True)

    return {"messages": [AIMessage(content=verdict.reply)], "guard": verdict.kind}


def reason(state: AgentState) -> dict:
    global _llm, _reasoning_effort
    messages = [SystemMessage(content=system_prompt()), *state["messages"]]
    try:
        return {"messages": [_get_llm().invoke(messages)]}
    except Exception as e:
        if _reasoning_effort != "none" and "reasoning" in str(e).lower():
            log.warning("Model rejected reasoning_effort=%s; falling back to none", _reasoning_effort)
            _reasoning_effort = "none"
            _llm = _build_llm()
            return {"messages": [_llm.invoke(messages)]}
        log.exception("Model call failed")
        return {
            "messages": [
                AIMessage(
                    content="Sorry — I lost that for a second. Could you say it once more?"
                )
            ]
        }


def output_guard(state: AgentState) -> dict:
    last = state["messages"][-1]
    if not isinstance(last, AIMessage) or not isinstance(last.content, str):
        return {}
    verdict = check_output(last.content)
    if not verdict.triggered:
        return {}
    log.info("Output guard tripped: %s", verdict.kind)
    return {"messages": [AIMessage(content=verdict.reply, id=last.id)], "guard": verdict.kind}


def after_input_guard(state: AgentState) -> Literal["reason", "__end__"]:
    return END if state.get("guard") else "reason"


def after_reason(state: AgentState) -> Literal["tools", "output_guard"]:
    last = state["messages"][-1]
    return "tools" if getattr(last, "tool_calls", None) else "output_guard"


def build_graph(checkpointer=None):
    graph = StateGraph(AgentState)
    graph.add_node("input_guard", input_guard)
    graph.add_node("reason", reason)
    graph.add_node("tools", ToolNode(ALL_TOOLS))
    graph.add_node("output_guard", output_guard)

    graph.add_edge(START, "input_guard")
    graph.add_conditional_edges("input_guard", after_input_guard)
    graph.add_conditional_edges("reason", after_reason)
    graph.add_edge("tools", "reason")
    graph.add_edge("output_guard", END)

    return graph.compile(checkpointer=checkpointer)


_compiled = None


def get_graph():
    global _compiled
    if _compiled is None:
        _compiled = build_graph(_make_checkpointer())
    return _compiled


def _make_checkpointer():
    """Postgres-backed checkpoints so a conversation survives a service restart.
    Falls back to memory if the store is unavailable — a demo that loses history is
    better than one that won't answer."""
    try:
        from langgraph.checkpoint.postgres import PostgresSaver
        from psycopg_pool import ConnectionPool

        conninfo = settings.database_url.replace("postgresql+psycopg://", "postgresql://")
        pool = ConnectionPool(conninfo, kwargs={"autocommit": True}, min_size=1, max_size=4)
        saver = PostgresSaver(pool)
        saver.setup()
        log.info("Using Postgres checkpointer")
        return saver
    except Exception:
        log.exception("Postgres checkpointer unavailable; using in-memory checkpoints")
        from langgraph.checkpoint.memory import MemorySaver

        return MemorySaver()


def run_turn(session: CallSession, user_text: str) -> dict:
    """Advance one conversational turn.

    Returns the reply plus the tools this turn invoked — the evaluation suite asserts on
    tool calls, since "did it refuse to book" is a fact about actions, not wording."""
    token = set_session(session)
    try:
        config = {
            "configurable": {"thread_id": session.id},
            "metadata": {
                "langfuse_session_id": session.id,
                "call_id": session.call_id,
                "verified": session.is_verified,
                "transport": session.transport,
            },
            "tags": ["maya", "voice-turn", session.transport],
        }
        if _langfuse_handler is not None:
            config["callbacks"] = [_langfuse_handler]

        result = get_graph().invoke(
            {"messages": [HumanMessage(content=user_text)], "guard": None}, config
        )
    finally:
        reset_session(token)

    messages = result["messages"]
    # Everything after the caller's turn belongs to this turn, not the checkpointed history.
    start = max(
        (i for i, m in enumerate(messages) if isinstance(m, HumanMessage)), default=len(messages) - 1
    )
    this_turn = messages[start:]

    tools_called = [
        call["name"]
        for message in this_turn
        if isinstance(message, AIMessage)
        for call in (getattr(message, "tool_calls", None) or [])
    ]
    reply = next(
        (
            m.content
            for m in reversed(this_turn)
            if isinstance(m, AIMessage) and isinstance(m.content, str) and m.content.strip()
        ),
        "Sorry, could you say that again?",
    )
    return {"reply": reply, "tools_called": tools_called, "guard": result.get("guard")}


def transcript_of(session: CallSession) -> list[BaseMessage]:
    state = get_graph().get_state({"configurable": {"thread_id": session.id}})
    return state.values.get("messages", []) if state else []


def seed_history(session: CallSession, prior: list[BaseMessage]) -> bool:
    """Backfill a conversation the voice platform remembers but we don't.

    ElevenLabs sends the whole transcript with every turn. Normally we ignore it — our
    checkpoint is the record, tool calls included — but if a turn arrives for a session
    with no checkpoint, the platform's transcript is the only memory there is. Without it
    Maya greets every turn as if it were the first, and a caller who has already said
    "I'm an existing patient" gets asked again. Returns True if anything was written."""
    if not prior:
        return False
    if transcript_of(session):
        return False
    config = {"configurable": {"thread_id": session.id}}
    # Attribute the backfill to the last node in the graph so the next turn starts from
    # START rather than resuming mid-workflow.
    get_graph().update_state(config, {"messages": prior, "guard": None}, as_node="output_guard")
    log.info("Seeded %d prior messages into session %s from the platform transcript", len(prior), session.id)
    return True
