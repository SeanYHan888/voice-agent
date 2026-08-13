#!/usr/bin/env python3
"""Push the Maya sprint backlog (docs/jira-backlog.md) to Jira.

Reads JIRA_SITE_URL, JIRA_EMAIL, JIRA_API_TOKEN from .env (repo root) or the
environment. Creates the project if missing, then epics, then stories under them.
Idempotent-ish: skips issues whose exact summary already exists in the project.

Usage: python3 scripts/push_jira_backlog.py [--project-key AVA] [--dry-run]
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

PROJECT_NAME = "AI Voice Agent"
DEFAULT_KEY = "AVA"

# (epic summary, [(story summary, acceptance criteria), ...])
BACKLOG: list[tuple[str, list[tuple[str, str]]]] = [
    ("E1 Architecture & Foundation", [
        ("Repo scaffold + Docker Compose skeleton",
         "docker compose up brings up gateway, auth, agent, domain, frontend, postgres; gateway health-routes to each service."),
        ("Postgres schema + models + seed",
         "Fresh compose up yields fully seeded DB: 4 providers, 2 visit types, 2-week slots, 20 mock patients, FAQ corpus. Zero real PII."),
        ("Nginx gateway routing",
         "/api/auth, /api/domain, /api/agent reachable through port 80 only; services not exposed directly."),
    ]),
    ("E2 Auth & Access Control", [
        ("Auth service: register/login/JWT",
         "PyJWT + bcrypt; roles patient/admin; JWT contains role; expiry enforced; admin bootstrapped."),
        ("Backend access control middleware",
         "Domain service validates JWT and scopes patient queries to own rows; patient A requesting patient B's data gets 403, proven by test."),
        ("Voice Verification flow (OTP)",
         "OTP issued via Twilio SMS to caller ID; verified Patient attached to Call session; scheduling tools refuse without verification; new-patient voice registration works."),
    ]),
    ("E3 Domain Service", [
        ("Scheduling APIs",
         "Search/book/reschedule/cancel; changes within 24h create Approval Tasks instead of executing; 24h rule enforced server-side with tests."),
        ("Calls, summaries, feedback APIs",
         "CRUD for calls, call summaries, feedback; feedback attaches to a Call by its own Patient only."),
        ("Admin task APIs",
         "Approval/escalation queues; approving a pending cancellation actually cancels the appointment."),
    ]),
    ("E4 Maya: LangGraph Voice Agent", [
        ("LangGraph conversation graph",
         "Intent routing + state checkpointing per Call using GPT-5.6 Luna; multi-turn text conversation books an appointment via tools in a local harness."),
        ("Scheduling + verification tools",
         "search_slots, book/reschedule/cancel_appointment, request/confirm_verification, register_new_patient, escalate_to_human; Pydantic-validated; identity enforced server-side in every tool."),
        ("FAQ RAG tool",
         "pgvector corpus + faq_lookup, anonymous-allowed; unknown topic yields honest miss."),
    ]),
    ("E5 Voice Transport", [
        ("OpenAI-compatible endpoint for ElevenLabs",
         "Agent service exposes chat-completions endpoint bridging to LangGraph; ElevenLabs round-trip conversation works."),
        ("Browser voice widget in portal",
         "Embedded widget with JWT-pre-verified session; logged-in patient books end-to-end by voice."),
        ("Twilio phone path (stretch)",
         "Number attached to ElevenLabs agent; OTP flow live; dialing from a verified phone reaches Maya and booking succeeds."),
    ]),
    ("E6 Patient Portal (React+TS+shadcn/ui)", [
        ("Auth pages + role-gated routing",
         "Login/register; patient/admin land on different homes; deep-link to a forbidden route bounces."),
        ("Appointments, call history, feedback pages",
         "Upcoming appointments, past calls with summaries, 1-5 star feedback per call; loading/success/error states on every fetch."),
    ]),
    ("E7 Admin Dashboard & Analysis Agents", [
        ("Dashboard charts",
         "Calls/day, booking conversion, avg feedback rendered from live DB."),
        ("Post-call pipeline agent",
         "On call end: summarize + tag intent and sentiment (GPT-5.6 Terra); every finished call gets a Call Summary visible in portal and dashboard."),
        ("Approval & escalation queue UI",
         "Approve/reject round-trips to domain service and executes or discards the gated change."),
        ("Analytics Q&A agent (cut-first)",
         "Guarded text-to-SQL: read-only role, table allowlist, SELECT-only; shows SQL alongside answer; refuses writes and off-allowlist tables."),
    ]),
    ("E8 Guardrails", [
        ("Medical-advice deflection + disclaimer", "Symptom/diagnosis questions get scripted deflection + disclaimer + offer to book or escalate; golden case passes."),
        ("Scope guard", "Off-topic requests politely refused; golden case passes."),
        ("Prompt-injection resistance", "Instructions in caller speech or RAG docs cannot override policy; golden case passes."),
    ]),
    ("E9 Observability", [
        ("LangFuse Cloud integration",
         "All three workflows traced: prompts, tool calls, graph steps, tokens/cost, latency; a booked call is fully inspectable as one trace."),
        ("Structured application logs",
         "Gateway + all services emit structured logs; request IDs correlate across services."),
    ]),
    ("E10 Golden Dataset & Evaluation", [
        ("Author ~25 golden cases",
         "JSON cases covering normal, edge, invalid, unsafe, and unauthorized scenarios with expected outcomes."),
        ("Eval runner",
         "One command runs the suite text-level against agent service; programmatic checks + LLM judge; pass/fail table exportable for slides."),
        ("Run, fix, rerun",
         "Weaknesses found and improvements made are documented with a before/after table."),
    ]),
    ("E11 Deployment", [
        ("EC2 t3.medium Compose deploy",
         "Public URL serves the app; Twilio/ElevenLabs webhooks round-trip in prod."),
        ("Local demo fallback",
         "Rehearsed full-local run that works with a Wi-Fi hotspot only."),
    ]),
    ("E12 Presentation", [
        ("Slide deck (19 required sections)", "Covers every section listed in the course PDF."),
        ("Demo script + rehearsal", "Browser spine, phone finale, fallback drill rehearsed end-to-end."),
        ("Jira hygiene + trainer access", "Board current and shared with will.wang@beaconfireinc.com and zack.yu@beaconfireinc.com."),
    ]),
]


def load_env() -> dict[str, str]:
    env = dict(os.environ)
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env.setdefault(k.strip(), v.strip())
    return env


class Jira:
    def __init__(self, site: str, email: str, token: str):
        self.base = site.rstrip("/")
        cred = base64.b64encode(f"{email}:{token}".encode()).decode()
        self.headers = {
            "Authorization": f"Basic {cred}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def call(self, method: str, path: str, body: dict | None = None) -> dict:
        req = urllib.request.Request(
            f"{self.base}{path}",
            data=json.dumps(body).encode() if body is not None else None,
            headers=self.headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(req) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:500]
            raise SystemExit(f"Jira {method} {path} -> HTTP {e.code}: {detail}")

    def adf(self, text: str) -> dict:
        return {
            "type": "doc",
            "version": 1,
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
        }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-key", default=DEFAULT_KEY)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    env = load_env()
    missing = [k for k in ("JIRA_SITE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN") if not env.get(k)]
    if missing:
        raise SystemExit(f"Missing in .env/environment: {', '.join(missing)}")

    if args.dry_run:
        n_stories = sum(len(s) for _, s in BACKLOG)
        print(f"Would create project {args.project_key}, {len(BACKLOG)} epics, {n_stories} stories.")
        return

    jira = Jira(env["JIRA_SITE_URL"], env["JIRA_EMAIL"], env["JIRA_API_TOKEN"])

    me = jira.call("GET", "/rest/api/3/myself")
    print(f"Authenticated as {me.get('displayName')} ({me.get('accountId')})")

    projects = jira.call("GET", f"/rest/api/3/project/search?query={args.project_key}")
    project = next((p for p in projects.get("values", []) if p["key"] == args.project_key), None)
    if project is None:
        project = jira.call("POST", "/rest/api/3/project", {
            "key": args.project_key,
            "name": PROJECT_NAME,
            "projectTypeKey": "software",
            "projectTemplateKey": "com.pyxis.greenhopper.jira:gh-simplified-scrum-classic",
            "leadAccountId": me["accountId"],
        })
        print(f"Created project {args.project_key}")
    else:
        print(f"Project {args.project_key} exists")

    # Existing summaries for idempotency (summary -> key)
    import urllib.parse

    existing: dict[str, str] = {}
    next_token = ""
    while True:
        params = {
            "jql": f"project = {args.project_key}",
            "fields": "summary",
            "maxResults": "100",
        }
        if next_token:
            params["nextPageToken"] = next_token
        page = jira.call("GET", f"/rest/api/3/search/jql?{urllib.parse.urlencode(params)}")
        for i in page.get("issues", []):
            existing[i["fields"]["summary"]] = i["key"]
        next_token = page.get("nextPageToken", "")
        if not next_token:
            break

    for epic_summary, stories in BACKLOG:
        if epic_summary in existing:
            epic_key = existing[epic_summary]
            print(f"= epic exists: {epic_key} {epic_summary}")
        else:
            epic = jira.call("POST", "/rest/api/3/issue", {
                "fields": {
                    "project": {"key": args.project_key},
                    "issuetype": {"name": "Epic"},
                    "summary": epic_summary,
                }
            })
            epic_key = epic["key"]
            print(f"+ epic {epic_key}: {epic_summary}")

        for story_summary, ac in stories:
            if story_summary in existing:
                print(f"  = story exists: {story_summary}")
                continue
            story = jira.call("POST", "/rest/api/3/issue", {
                "fields": {
                    "project": {"key": args.project_key},
                    "issuetype": {"name": "Story"},
                    "summary": story_summary,
                    "description": jira.adf(f"Acceptance criteria: {ac}"),
                    "parent": {"key": epic_key},
                }
            })
            print(f"  + story {story['key']}: {story_summary}")

    print("Done.")


if __name__ == "__main__":
    main()
