"""The analytics agent: a second LangGraph workflow that answers an admin's question
about clinic operations.

    START → write_sql → run_sql ─(rejected, first try)→ write_sql
                          │
                       (ok / gave up)
                          ↓
                       explain → END

The retry edge matters: a generated query that the domain service refuses comes back with
the reason attached, and the model gets one chance to repair it. The domain service is the
authority on what may run — this side never executes anything itself.
"""
import logging
import re
from typing import Literal, TypedDict

import httpx
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph

from .config import settings
from .graph import _langfuse_handler

log = logging.getLogger(__name__)

SQL_PROMPT = """You write PostgreSQL for a dermatology clinic's operations dashboard.

Schema:
{schema}

Question: {question}
{repair}

Rules:
- One SELECT statement. No writes of any kind.
- Only the tables above.
- Prefer readable column aliases; round averages to 2 decimals.
- Today is CURRENT_DATE. Timestamps are timestamptz.

Reply with the SQL only — no explanation, no markdown fences."""

ANSWER_PROMPT = """Question: {question}

SQL that ran:
{sql}

Rows returned ({count}):
{rows}

Answer the question in one or two plain sentences for a clinic manager. Quote the actual
numbers. If no rows came back, say the data doesn't show any. Don't mention SQL."""


class AnalyticsState(TypedDict):
    question: str
    schema: str
    token: str
    sql: str
    error: str
    attempts: int
    rows: list[dict]
    row_count: int
    answer: str


def _llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.analysis_model, api_key=settings.openai_api_key, timeout=60, max_retries=2
    )


def _strip_fences(text: str) -> str:
    return re.sub(r"^```(?:sql)?|```$", "", text.strip(), flags=re.MULTILINE).strip()


def write_sql(state: AnalyticsState) -> dict:
    repair = (
        f"\nYour previous attempt was rejected: {state['error']}\nPrevious SQL:\n{state['sql']}\nFix it."
        if state.get("error")
        else ""
    )
    prompt = SQL_PROMPT.format(schema=state["schema"], question=state["question"], repair=repair)
    sql = _strip_fences(str(_llm().invoke(prompt).content))
    return {"sql": sql, "attempts": state.get("attempts", 0) + 1}


def run_sql(state: AnalyticsState) -> dict:
    try:
        response = httpx.post(
            f"{settings.domain_service_url}/admin/query",
            headers={"Authorization": f"Bearer {state['token']}"},
            json={"sql": state["sql"]},
            timeout=30,
        )
    except Exception as e:
        return {"error": f"could not reach the database service: {e}"}

    if response.status_code >= 400:
        detail = response.json().get("detail", response.text)
        return {"error": str(detail)}
    payload = response.json()
    return {
        "rows": payload["rows"],
        "row_count": payload["row_count"],
        "sql": payload["sql"],
        "error": "",
    }


def after_run(state: AnalyticsState) -> Literal["write_sql", "explain"]:
    return "write_sql" if state.get("error") and state["attempts"] < 2 else "explain"


def explain(state: AnalyticsState) -> dict:
    if state.get("error"):
        return {"answer": f"I couldn't answer that one — the query was refused: {state['error']}"}
    rows = state["rows"][:30]
    prompt = ANSWER_PROMPT.format(
        question=state["question"],
        sql=state["sql"],
        count=state["row_count"],
        rows="\n".join(str(row) for row in rows) if rows else "(none)",
    )
    return {"answer": str(_llm().invoke(prompt).content).strip()}


def build_analytics_graph():
    graph = StateGraph(AnalyticsState)
    graph.add_node("write_sql", write_sql)
    graph.add_node("run_sql", run_sql)
    graph.add_node("explain", explain)
    graph.add_edge(START, "write_sql")
    graph.add_edge("write_sql", "run_sql")
    graph.add_conditional_edges("run_sql", after_run)
    graph.add_edge("explain", END)
    return graph.compile()


_compiled = None


def ask(question: str, admin_token: str) -> dict:
    global _compiled
    if _compiled is None:
        _compiled = build_analytics_graph()

    try:
        schema_response = httpx.get(
            f"{settings.domain_service_url}/admin/query/schema",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=15,
        )
        schema_response.raise_for_status()
        schema = schema_response.json()["schema"]
    except Exception as e:
        log.exception("Could not load schema")
        return {"answer": "I couldn't reach the clinic database just now.", "sql": None, "error": str(e)}

    config = {"tags": ["maya", "analytics-agent"], "metadata": {"question": question}}
    if _langfuse_handler is not None:
        config["callbacks"] = [_langfuse_handler]

    result = _compiled.invoke(
        {
            "question": question,
            "schema": schema,
            "token": admin_token,
            "sql": "",
            "error": "",
            "attempts": 0,
            "rows": [],
            "row_count": 0,
            "answer": "",
        },
        config,
    )
    return {
        "answer": result["answer"],
        "sql": result.get("sql"),
        "row_count": result.get("row_count", 0),
        "rows": result.get("rows", [])[:20],
        "attempts": result.get("attempts", 1),
        "error": result.get("error") or None,
    }
