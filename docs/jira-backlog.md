# Jira Backlog — Maya (Patient Access Voice Agent)

One-week sprint, Aug 11–17 2026. Sprint goal: **a live, demoable voice agent that schedules appointments for a mock clinic, with the full course rubric (LangGraph, LangFuse, guardrails, Golden Dataset, access control) demonstrable end-to-end.**

Status workflow: To Do → In Progress → In Review → Blocked → Done. All tickets assigned to the solo member. This file is the source of truth for pushing to Jira via REST API; epic/story keys get filled in after creation.

---

## E1 — Architecture & Foundation

- **E1-1 Repo scaffold + Docker Compose skeleton** — monorepo with `gateway/`, `services/auth`, `services/agent`, `services/domain`, `frontend/`, `docker-compose.yml`; all containers build and start. *AC: `docker compose up` brings up gateway, 3 services, postgres; gateway health-routes to each service.*
- **E1-2 Postgres schema + migrations + seed** — SQLAlchemy models per SPEC data sketch; seed script generates 4 providers, 2-week slots, ~20 mock patients, FAQ corpus. *AC: fresh `compose up` yields a fully seeded DB; zero real PII.*
- **E1-3 Nginx gateway routing** — `/api/auth`, `/api/agent`, `/api/domain` proxied; React build served at `/`. *AC: all routes reachable through port 80 only; services not exposed directly.*

## E2 — Auth & Access Control

- **E2-1 Auth service: register/login/JWT** — PyJWT + bcrypt, roles `patient`/`admin`. *AC: JWT contains role + patient link; expiry enforced.*
- **E2-2 Backend access control middleware** — domain-service validates JWT, scopes patient queries to own rows; admin endpoints require `admin`. *AC: patient A requesting patient B's data → 403, proven by test.*
- **E2-3 Voice Verification flow** — OTP issue (Twilio SMS to caller ID) + confirm; verified Patient attached to Call session; new-patient voice registration. *AC: scheduling tools refuse without verification; OTP round-trip works on a verified trial number.*

## E3 — Domain Service

- **E3-1 Scheduling APIs** — search slots, book, reschedule, cancel; <24h changes create Approval Tasks instead of executing. *AC: 24h rule enforced server-side with tests.*
- **E3-2 Calls / summaries / feedback APIs** — CRUD for calls, call summaries, feedback (patient-scoped). *AC: feedback attaches to a Call by its Patient only.*
- **E3-3 Admin task APIs** — approval/escalation queues; approve/reject executes or discards the gated change. *AC: approving a pending cancellation actually cancels.*

## E4 — Maya: LangGraph Voice Agent (core)

- **E4-1 LangGraph conversation graph** — intent routing, state checkpointing per Call, GPT-5.6 Luna. *AC: multi-turn text conversation books an appointment via tools in a local harness.*
- **E4-2 Scheduling + verification tools** — `search_slots`, `book/reschedule/cancel_appointment`, `request/confirm_verification`, `register_new_patient`, `escalate_to_human`, Pydantic-validated. *AC: every tool enforces identity server-side.*
- **E4-3 FAQ RAG tool** — pgvector corpus, `faq_lookup`, anonymous-allowed. *AC: FAQ answered without verification; unknown topic → honest miss.*

## E5 — Voice Transport

- **E5-1 OpenAI-compatible endpoint for ElevenLabs** — agent-service exposes chat-completions endpoint bridging to LangGraph. *AC: ElevenLabs agent config points at it; round-trip conversation works.*
- **E5-2 Browser voice widget in portal** — embedded, JWT-pre-verified session. *AC: logged-in patient talks to Maya and books, end-to-end.*
- **E5-3 Twilio phone path** — number attached to ElevenLabs agent; OTP flow live. *AC: dialing the number from a verified phone reaches Maya; booking succeeds. (Stretch: cut if time runs out.)*

## E6 — Patient Portal (React + TS + shadcn/ui)

- **E6-1 Auth pages + routing** — login/register, role-gated routes (React Router). *AC: patient/admin land on different homes; deep-link to forbidden route bounces.*
- **E6-2 Appointments + call history + feedback pages** — upcoming appointments, past calls with summaries, 1–5 star feedback per call. *AC: loading/success/error states on every fetch.*

## E7 — Admin Dashboard & Analysis Agents

- **E7-1 Dashboard charts** — calls/day, booking conversion, avg feedback (plain SQL). *AC: renders from live DB.*
- **E7-2 Post-call pipeline agent** — on call end: summarize, tag intent + sentiment (Terra), store Call Summary. *AC: every finished call gets a summary visible in portal + dashboard.*
- **E7-3 Approval & escalation queues UI** — human-in-the-loop resolution. *AC: approve/reject round-trips to domain-service.*
- **E7-4 Analytics Q&A agent** — guarded text-to-SQL (read-only role, allowlist, SELECT-only), shows SQL alongside answer. *AC: refuses writes and off-allowlist tables. (Cut-first item.)*

## E8 — Guardrails

- **E8-1 Medical-advice deflection + disclaimer** · **E8-2 Scope guard** · **E8-3 Prompt-injection resistance (speech + RAG docs)** — each with a Golden Dataset case proving it. *AC: corresponding golden cases pass.*

## E9 — Observability

- **E9-1 LangFuse Cloud integration** — all three workflows traced: prompts, tool calls, graph steps, tokens/cost, latency. *AC: a booked call is fully inspectable as one trace.*
- **E9-2 Application logs** — structured logs in gateway + all services. *AC: request IDs correlate across services.*

## E10 — Golden Dataset & Evaluation

- **E10-1 Author ~25 cases** (JSON, per SPEC categories). *AC: covers normal, edge, invalid, unsafe, unauthorized.*
- **E10-2 Eval runner** — text-level against agent-service; programmatic checks + LLM judge; pass/fail table output. *AC: one command runs the suite; results exportable for slides.*
- **E10-3 Run → fix → rerun** — document weaknesses found and improvements made. *AC: before/after table exists.*

## E11 — Deployment

- **E11-1 EC2 t3.medium + Compose deploy** — public URL; webhook targets for Twilio/ElevenLabs. *AC: public URL serves the app; a phone call round-trips in prod.*
- **E11-2 Local demo fallback** — rehearsed full-local run. *AC: works with Wi-Fi hotspot only.*

## E12 — Presentation

- **E12-1 Slide deck** (all 19 PDF-required sections) · **E12-2 Demo script + rehearsal** (browser spine, phone finale, fallback drill) · **E12-3 Jira hygiene** (board current, shared with will.wang@ / zack.yu@beaconfireinc.com).
