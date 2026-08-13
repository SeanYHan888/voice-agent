# Maya — Patient Access Voice Agent

Solo final project for the Beacon Fire June Python GenAI course. Presentation: **Aug 17, 2026, 2 PM ET** (90 min + live demo). Modeled on [Assort Health](https://www.assorthealth.com/); built against a mock clinic. Vocabulary lives in [CONTEXT.md](../CONTEXT.md); architectural decisions in [docs/adr/](./adr/).

## Business problem

Medical clinics lose appointments and burn staff time on phone volume. Maya is an AI voice front door for **Assort Dermatology** (mock): she answers every call instantly, schedules appointments, answers clinic FAQs, and escalates to humans when she should not act alone. Out of scope (deliberately): refills, referrals, insurance eligibility, outbound outreach, waitlists, intake forms.

## Actors & identity

| Actor | Channel | Identity mechanism |
|---|---|---|
| Caller | Phone / browser voice widget | None yet — anonymous |
| Patient | Voice (after Verification) or portal | Phone: SMS OTP against caller ID (Twilio). Web: JWT session |
| Admin | Portal dashboard | JWT session, `admin` role |

**Lazy verification:** FAQs are answered anonymously. The moment a conversation touches a patient record (search-as-me, book, reschedule, cancel), the agent requires a verified Patient on the session. Unknown callers can register as a new Patient by voice (name + DOB). Enforcement lives in the **tool layer** — every scheduling tool checks session identity server-side. The prompt is never the security boundary.

## Voice architecture (ADR 0001)

ElevenLabs Agents is the audio shell (STT, TTS, turn-taking, barge-in, native Twilio telephony). Its LLM points at the Agent Service's OpenAI-compatible endpoint, where the LangGraph workflow runs. Two transports, one brain:

- **Browser widget** embedded in the logged-in portal (JWT pre-verified) — demo spine.
- **Twilio phone number** with SMS OTP verification — demo finale. Trial account: verify all demo phone numbers in the Twilio console on day 1.

## Models

- **Voice turns:** OpenAI GPT-5.6 **Luna**, reasoning minimal (latency budget < 1s to first token).
- **Post-call pipeline & analytics agent:** GPT-5.6 **Terra**.

## Services (Docker Compose)

| Container | Role |
|---|---|
| `gateway` | Nginx: routes `/api/auth`, `/api/agent`, `/api/domain`; serves React build |
| `auth-service` | FastAPI: register/login, JWT issue/verify (PyJWT + bcrypt), roles `patient`/`admin` |
| `agent-service` | FastAPI: LangGraph workflows; OpenAI-compatible endpoint for ElevenLabs; OTP issuance (Twilio); LangFuse tracing |
| `domain-service` | FastAPI + SQLAlchemy: patients, providers, slots, appointments, calls, summaries, feedback, admin tasks; business APIs used by agent tools and frontend |
| `frontend` | React + TypeScript + **shadcn/ui** (+ Tailwind), React Router; built and served via gateway |
| `postgres` | Postgres 16 + pgvector (FAQ corpus embeddings) |

External: LangFuse Cloud, ElevenLabs, Twilio, OpenAI.

## Data model (sketch)

`patients` (name, dob, phone, user_id?) · `users` (email, password_hash, role) · `providers` · `visit_types` (New Patient 30m, Follow-up 15m) · `slots` (provider, start, visit_type, status) · `appointments` (patient, slot, status) · `calls` (patient?, transport, started/ended, transcript) · `call_summaries` (call, summary, intent, sentiment) · `feedback` (call, patient, stars, comment) · `admin_tasks` (kind: `approval` | `escalation`, payload, status, resolution) · `faq_chunks` (text, embedding).

Seed: 4 providers, 2-week slot inventory, ~20 mock patients, ~15 FAQ documents. All data AI-generated/mock — no real PII.

## LangGraph workflows (all traced to LangFuse Cloud)

1. **Maya (voice agent):** conversational graph — intent routing → guardrail nodes → tools: `search_slots`, `book_appointment`, `reschedule_appointment`, `cancel_appointment`, `request_verification` (sends OTP), `confirm_verification`, `register_new_patient`, `faq_lookup` (pgvector RAG), `escalate_to_human`. Conversation state checkpointed per Call.
2. **Post-call pipeline:** on call end → summarize transcript → tag intent + sentiment → write Call Summary.
3. **Analytics agent:** admin natural-language question → guarded text-to-SQL (read-only DB role, table allowlist, SELECT-only validation) → answer + the SQL it ran. *(Cut-first item if the week runs short.)*

## Human-in-the-loop

- Cancel/reschedule **within 24h** of the Appointment → becomes an Approval Task; Maya tells the caller it's pending staff review. Admin approves/rejects in the dashboard; resolution executes the change.
- Escalations (medical questions, distressed caller, agent stuck) → Escalation task with callback context.

## Guardrails

1. **No medical advice** — symptom/diagnosis questions get a scripted deflection + disclaimer + offer to book or escalate.
2. **Scope guard** — off-topic requests politely refused.
3. **Tool-layer access control** — verified-Patient check on every scheduling tool; patients touch only their own rows.
4. **Prompt-injection resistance** — caller speech and FAQ documents cannot override policy (Golden Dataset case proves it).
5. **Structured-output validation** — Pydantic on every tool argument.
6. **Analytics agent containment** — read-only role + SQL allowlist.

## Golden Dataset

~25 cases, JSON, run at text level against the Agent Service (transport bypassed). Categories: booking happy paths, reschedule/cancel, <24h policy edge, unverified-access attempt (must refuse), medical-advice bait (must deflect), prompt injection, FAQ hit, FAQ miss (must admit ignorance), invalid/garbage input, new-patient registration. Scoring: programmatic checks (tool called with right args / correct refusal) + LLM judge for tone. Runner produces a pass/fail table for the slides.

## Frontend pages

- **Patient portal:** login/register · upcoming appointments · call history with Call Summaries · per-call Feedback (1–5 stars + comment) · embedded voice widget. Voice is the only write path for scheduling.
- **Admin dashboard:** charts (calls/day, booking conversion, avg feedback) · Approval Task queue · Escalation queue · analytics Q&A chat.
- Role-gated routes on the frontend, enforced again on the backend.

## Deployment

Docker Compose on a paid **t3.medium** EC2 (public URL doubles as the Twilio/ElevenLabs webhook target). LangFuse Cloud (no self-hosting). Fully local Compose demo is the rehearsed fallback. Dev-time webhooks via ngrok.

## Sprint plan (6 days)

| Day | Focus |
|---|---|
| Aug 11 | Repo scaffold, Compose skeleton, DB schema + seed, auth-service, Jira populated & shared with trainers |
| Aug 12 | Domain-service APIs; Maya's LangGraph core + tools (text-only harness); LangFuse wired |
| Aug 13 | ElevenLabs custom-LLM bridge; browser widget in portal; OTP verification flow (Twilio SMS) |
| Aug 14 | Portal pages (shadcn/ui); post-call pipeline; admin dashboard + approval/escalation queues |
| Aug 15 | Analytics agent; guardrail hardening; Golden Dataset authored + first full run |
| Aug 16 | EC2 deploy; phone path end-to-end; eval rerun + fixes; slide deck |
| Aug 17 AM | Rehearsal (browser + phone), buffer. **Present 2 PM ET** |

## Risks

- **Live phone demo fails in the room** → browser widget is the rehearsed spine; phone is the finale with instant fallback.
- **ElevenLabs custom-LLM latency too high** → drop voice-turn reasoning to zero, trim system prompt, cache greeting audio.
- **Solo time crunch** → cut order: analytics agent → phone transport (browser only) → chart polish. Never cut: LangGraph centrality, LangFuse, guardrails, Golden Dataset, access control.
