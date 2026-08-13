"""Read-only query surface for the analytics agent.

Three independent barriers, because a generated query is untrusted input: the statement
must parse as a single SELECT, every table it names must be on the allowlist, and it runs
inside a READ ONLY transaction so the database itself rejects a write that slipped past
the first two.
"""
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from ..auth import Principal, require_admin
from ..db import engine

router = APIRouter(prefix="/admin", tags=["analytics"])

ALLOWED_TABLES = {
    "patients",
    "providers",
    "visit_types",
    "slots",
    "appointments",
    "calls",
    "call_summaries",
    "feedback",
    "admin_tasks",
}

FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|copy|vacuum|"
    r"pg_sleep|pg_read_file|dblink)\b",
    re.IGNORECASE,
)
TABLE_REFERENCE = re.compile(r"\b(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_]*)", re.IGNORECASE)
MAX_ROWS = 200

SCHEMA_DESCRIPTION = """patients(id, first_name, last_name, dob, phone, user_id, created_at)
providers(id, name, title)
visit_types(id, name, duration_minutes)  -- 'New Patient' 30min, 'Follow-up' 15min
slots(id, provider_id, visit_type_id, starts_at, status)  -- status: open | booked
appointments(id, patient_id, slot_id, status, call_id, created_at)  -- status: booked | cancelled | pending_change
calls(id, patient_id, transport, caller_phone, started_at, ended_at, transcript)
call_summaries(id, call_id, summary, intent, sentiment, created_at)
  -- intent: booking | reschedule | cancellation | clinic_info | medical_question | complaint | other
  -- sentiment: positive | neutral | negative
feedback(id, call_id, patient_id, stars, comment, created_at)  -- stars 1..5
admin_tasks(id, kind, status, payload, call_id, created_at, resolved_at)
  -- kind: approval | escalation; status: open | approved | rejected | done"""


class QueryIn(BaseModel):
    sql: str


def validate_sql(sql: str) -> str:
    """Returns the statement to run, or raises with the reason it was refused."""
    cleaned = sql.strip().rstrip(";").strip()
    if not cleaned:
        raise HTTPException(400, "Empty query")
    if ";" in cleaned:
        raise HTTPException(400, "Only a single statement is allowed")
    if not re.match(r"^(select|with)\b", cleaned, re.IGNORECASE):
        raise HTTPException(400, "Only SELECT queries are allowed")
    if FORBIDDEN.search(cleaned):
        raise HTTPException(400, "Query contains a forbidden keyword")

    referenced = {t.lower() for t in TABLE_REFERENCE.findall(cleaned)}
    # CTE names are defined inline, so they are not tables that need allowlisting.
    cte_names = {n.lower() for n in re.findall(r"(?:with|,)\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+as\s*\(", cleaned, re.IGNORECASE)}
    unknown = referenced - ALLOWED_TABLES - cte_names
    if unknown:
        raise HTTPException(400, f"Query touches tables that are not permitted: {', '.join(sorted(unknown))}")

    if not re.search(r"\blimit\b", cleaned, re.IGNORECASE):
        cleaned = f"{cleaned} LIMIT {MAX_ROWS}"
    return cleaned


@router.get("/query/schema")
def schema(_: Principal = Depends(require_admin)):
    return {"schema": SCHEMA_DESCRIPTION, "tables": sorted(ALLOWED_TABLES)}


@router.post("/query")
def run_query(body: QueryIn, _: Principal = Depends(require_admin)):
    statement = validate_sql(body.sql)
    try:
        with engine.connect() as connection:
            connection.execute(text("SET TRANSACTION READ ONLY"))
            result = connection.execute(text(statement))
            rows = [dict(row) for row in result.mappings().all()[:MAX_ROWS]]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"Query failed: {str(e).splitlines()[0][:300]}")
    return {"sql": statement, "row_count": len(rows), "rows": rows}
