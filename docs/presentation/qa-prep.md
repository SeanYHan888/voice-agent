# Maya — Q&A prep for the technical presentation

Likely trainer questions, with answers grounded in the code. Each answer names the file
that backs it up so you can open it live if asked.

---

## Architecture & LangGraph

**Q: Why LangGraph instead of a single prompt or a plain tool-calling loop?**
Four things the graph gives that a hand-rolled loop doesn't:
1. Deterministic guard nodes on both sides of the model — `input_guard` can route straight
   to END without the LLM ever being called.
2. A resumable tool loop (`reason ⇄ tools`) — the model can chain as many tool calls as it
   needs and every hop is a node.
3. Per-node tracing in LangFuse.
4. Checkpointed state per call via `PostgresSaver`, keyed by the call-session id — a
   restart restores both the transcript and who the caller is.
→ `services/agent/app/graph.py`

**Q: Walk me through the graph.**
`START → input_guard`. Conditional edge `after_input_guard`: if `state["guard"]` is set → END,
else → `reason`. `reason` runs GPT‑5.6 Luna with the 11 tools bound. Conditional edge
`after_reason`: if the AIMessage has `tool_calls` → `tools` (a `ToolNode`) → back to `reason`;
otherwise → `output_guard` → END. State is `AgentState(messages, guard, identity)`.
→ `graph.py` lines ~53–58 (state), ~157–177 (routing + edges)

**Q: What is in the state, and why isn't the system prompt stored?**
`messages` (with `add_messages`), `guard` (which guard fired), `identity` (a snapshot of the
CallSession). The system prompt is rebuilt on every `reason()` with today's date and the
verified caller's first name — storing it would freeze the date and leak stale identity into
later turns.
→ `graph.py` `reason()`, `prompts.py` `system_prompt()`

**Q: How many LangGraph workflows are there? Is the summariser one?**
Two `StateGraph`s: Maya's conversation graph and the analytics graph
(`write_sql → run_sql → explain` with a one-shot repair edge). The post-call summariser is a
single Terra call wrapped by trigger plumbing — I don't claim it as a graph. All three are
traced to LangFuse.
→ `graph.py`, `analytics.py`, `summarizer.py`

**Q: Why two models?**
Luna with `reasoning_effort="none"` for voice turns because first-token latency must be
sub-second (measured median 1.7 s per turn including tools). Terra for the summariser,
analytics SQL, and the eval judge — nobody is waiting, quality matters more.
→ `config.py` (`voice_model`, `analysis_model`), `evals/run_eval.py` (`JUDGE_MODEL`)

**Q: What is the checkpointer and what happens if Postgres is down?**
`PostgresSaver` over a psycopg pool on the same DATABASE_URL; `saver.setup()` creates
`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`. `thread_id` = call-session id. If the
pool can't be created it falls back to `MemorySaver` and logs — the service stays up.
→ `graph.py` `_make_checkpointer()`

---

## Tools, identity, access control

**Q: What stops the model from booking for someone else, or from claiming to be a nurse?**
No tool takes a patient id. Identity lives in the server-side `CallSession`, set only by
`finish_verification` / `register_new_patient` (or a portal JWT at session start). Tools read
it from a contextvar and mint a signed token; the domain service resolves a `Principal` from
that token — no `patient_id` claim ⇒ `require_patient_identity` returns 403. Even if the
model were persuaded, the tool layer and the domain service refuse. Claimed authority is
also caught by the `identity_claim` guard before the model runs.
→ `tools.py` (contextvar, `VERIFY_FIRST`), `session.py` `token()`, `domain/app/auth.py`

**Q: What triggers `POST /appointments`? Does the LLM write SQL for bookings?**
Only the `book_appointment` tool (and admins/tests carrying an admin JWT). The LLM's only
contribution is choosing the tool and a `slot_id`; the SQL is fixed SQLAlchemy in the domain
handler. Generated SQL exists only in the analytics agent, which is read-only.
→ `tools.py` `book_appointment`, `domain_client.py`, `domain/app/routers/scheduling.py`

**Q: How do you prevent double-booking?**
Two layers: `SELECT … FOR UPDATE` on the slot row inside the booking transaction, and a
partial unique index `appointments(slot_id) WHERE status IN ('booked','pending_change')`.
The index replaced a blanket unique constraint after the eval found a cancelled slot could
never be rebooked.
→ `scheduling.py` `book()`, `models.py` `uq_slot_live_appointment`

**Q: Where is the human-in-the-loop?**
Cancel/reschedule inside 24 h don't execute: the appointment flips to `pending_change` and
an `admin_tasks` row (kind=`approval`) is created. Approving in the staff queue performs the
change (fresh row lock for reschedules); rejecting restores `booked`. Escalations (medical,
complaint, out-of-scope) use the same table with kind=`escalation`.
→ `scheduling.py` `APPROVAL_WINDOW`, `routers/admin.py` approve/reject, `routers/calls.py` `/escalations`

**Q: How do JWT roles work across services?**
Auth issues HS256 JWTs (`sub`, `email`, `role`, 12 h). The agent mints its own HS256
call-session token (`role=agent`, `call_id`, `patient_id` when verified, 1 h). Same shared
secret; the domain service turns either into a `Principal` and applies `require_admin`,
`require_patient_identity`, `owns_or_admin`. Frontend `RequireRole` only saves a round trip.
→ `auth/app/security.py`, `session.py`, `domain/app/auth.py`, `frontend/src/lib/auth.tsx`

**Q: Why HS256 with a shared secret rather than RS256?**
Solo one-week sprint, one Compose file, one secret to rotate. RS256 is on the next list so
services can verify without holding the signing key.

**Q: How does a portal user get linked to a clinic patient record?**
`POST /patients/claim` with phone + DOB; normalised phone and exact DOB must match; 409 if
the record already belongs to a different account; sets `patients.user_id`. Admin can unlink.
On every request a patient-role Principal is resolved by `patients.user_id = sub`.
→ `domain/app/routers/patients.py`, `domain/app/auth.py`

---

## Guardrails

**Q: Your guardrails are regex — isn't that weak?**
They're the outer layer, chosen because they're deterministic, free, and identical every run
— exactly the properties you want for anything safety-critical. The real boundary is the
tool-layer identity check and the domain Principal, which hold regardless of what the model
says. There's also an output guard on diagnostic language and `sanitise_retrieved` on FAQ
hits. Next step is an LLM-judge guard behind the regex layer.
→ `guardrails.py`, `graph.py` `input_guard()` / `output_guard()`

**Q: What are the six guardrails and how do you prove they work?**
No medical advice · emergency routing · prompt-injection resistance · identity-claim refusal
· scope guard · SQL containment. Each has Golden Dataset cases (`unsafe` / `unauthorized`);
the guard kind is returned in the chat response so the eval asserts on it deterministically.
→ `evals/golden_dataset.json`, `evals/run_eval.py`

**Q: In what order do the input guards run?**
emergency → identity_claim → prompt_injection → medical_advice → out_of_scope; first match
wins. Emergency/medical/out-of-scope also create an escalation task with the caller's text.
→ `guardrails.py` `check_input()`

**Q: How do you handle prompt injection through retrieved documents?**
Every FAQ hit passes through `sanitise_retrieved`; anything matching the injection patterns
is replaced with `[clinic document omitted: contained instruction-like content]` before the
model sees it.
→ `guardrails.py` `sanitise_retrieved()`, `tools.py` `lookup_clinic_info`

**Q: What happens if the model hallucinates a booking or a policy?**
It can't confirm a booking: the confirmation text comes from the tool result, and the
appointment either exists in Postgres or the tool errored. Same for the 24 h rule — Maya
reports "held for review" only when the tool returns `requires_approval`; the eval caught her
applying the rule herself from the FAQ text, and I fixed it.

**Q: What happens on failures — model down, tool error, no API key?**
Tool errors come back as text the model can recover from ("that time was just taken — offer
another"). A model failure returns "could you say that once more?" rather than a dead line;
if the model rejects the reasoning parameter it's rebuilt without it. A missing OpenAI key
degrades conversation but doesn't stop the service; retrieval simply returns nothing.
→ `graph.py` `reason()`, `domain_client.py` `DomainError`, `domain/app/faq.py`

---

## Microservices, gateway, data

**Q: Why three services and where's the boundary?**
Identity (auth), business rules (domain), reasoning (agent). The agent owns no business
tables — every action is a domain API call, so the same rules apply to humans and agents.
Auth knows nothing about patients; the account→record link lives in domain.

**Q: They share one Postgres — is that really microservices?**
One physical database for a solo sprint, but separate SQLAlchemy bases and no cross-service
foreign keys (`patients.user_id` is a plain int by design), so splitting is a config change.
The agent's only tables are LangGraph checkpoints.
→ `domain/app/models.py` comment on `user_id`

**Q: How does the gateway work?**
Nginx: `/api/auth`, `/api/domain`, `/api/agent` prefixes rewritten and proxied to services on
the Compose network; SPA at `/`; TLS terminated at the gateway; `X-Request-Id` minted per
request and logged by every service. Upstreams are variables so Nginx re-resolves container
IPs every 10 s. Only 80/443 are published; `/api/agent` has a 300 s read timeout for streams.
→ `gateway/nginx.conf`, `gateway/proxy_common.conf`, `gateway/nginx-https.conf.template`

**Q: Sync HTTP everywhere — why no message queue?**
The only async work is the post-call pipeline; a FastAPI background task plus an idle-sweep
thread was sufficient at this scale and one less container to explain. RabbitMQ is the stated
next step for volume.
→ `agent/app/main.py` (`wrapup`, `sweep_idle_sessions`)

**Q: How is the schema managed and seeded?**
`Base.metadata.create_all` at startup plus an idempotent `seed.py` (4 providers, 2 visit
types, 20 fictional patients, 15 FAQ docs, ~760 slots over 14 weekdays plus 4 near-term slots
so the 24 h rule is always demoable). No Alembic yet — listed as a limitation.
→ `domain/app/main.py`, `domain/app/seed.py`

**Q: Describe the data model in one breath.**
`patients` (with `user_id` → auth users, no FK) · `providers` · `visit_types` · `slots`
(unique per provider+start) · `appointments` (partial unique index on live rows) · `calls` ·
`call_summaries` (1:1) · `feedback` (1:1) · `admin_tasks` (approval | escalation, JSON payload)
· `verification_codes` · `faq_chunks` (`vector(1536)`) — plus auth's `users` and LangGraph's
checkpoint tables. All enums are strings validated in Pydantic.
→ `domain/app/models.py`, `auth/app/models.py`

---

## RAG

**Q: Describe the retrieval pipeline.**
15 clinic docs, one chunk each, embedded with `text-embedding-3-small` (1536-d) into a
pgvector column at startup; cosine-distance search (`<=>`), top‑3, relevance cutoff 0.75 so
off-topic questions return `[]` and Maya says she doesn't know. No ANN index because it's 15
rows; chunking + HNSW when the corpus grows.
→ `domain/app/faq.py`

**Q: Why not let the model answer clinic questions from its own knowledge?**
Because clinic policy is the clinic's, not the model's — hallucinated hours or cancellation
rules are exactly the failure a clinic can't accept. And the docs are what Maya *says*; the
tools are what *decides*.

**Q: Why is `/faq/search` public?**
Hours and parking need no identity — that's the anonymous FAQ path, and it's what lets a
first-time caller get help before verifying.

---

## Voice / ElevenLabs

**Q: What does ElevenLabs do vs. what do you do?**
ElevenLabs is STT, TTS, turn-taking, barge-in. Its LLM setting points at my
OpenAI-compatible endpoint, so every turn runs through LangGraph. That's ADR 0001; the
rejected options were fully-managed ElevenLabs (sidelines LangGraph) and a raw Twilio media
pipeline (too much for a one-week solo build).
→ `docs/adr/0001-elevenlabs-voice-shell-langgraph-brain.md`, `agent/app/main.py` `/v1/chat/completions`

**Q: How does the widget know who the patient is?**
It doesn't get the JWT. The browser calls `POST /agent/session` with the portal JWT; the agent
decodes it server-side, resolves `GET /patients/me`, and returns a `session_id`. Only that id
goes to the widget (`user-id` + `dynamic-variables` + the `elevenlabs-convai:call` event), and
the agent maps it back to the verified session — it's also the LangGraph `thread_id` and the
LangFuse `session_id`.
→ `frontend/src/components/MayaPanel.tsx`, `agent/app/main.py` `_extract_session_id`

**Q: How does the OpenAI-compatible endpoint work?**
Bearer key checked with `hmac.compare_digest`; session id extracted from headers/body in a
fixed candidate order; only the last user message is scored; the platform transcript is
back-filled into the checkpoint if it's empty; response is either a normal chat.completion
object or exactly three SSE frames (content chunk, stop chunk, `[DONE]`).
→ `agent/app/main.py`

**Q: What if two turns overlap (barge-in)?**
One `threading.Lock` per session serialises them, and a resend whose last message isn't the
user's returns the greeting instead of re-executing an action.
→ `session.py` `lock_for()`, `main.py` `_last_user_message`

**Q: Why no real phone number?**
Twilio requires a business profile. Transport is already a field on the CallSession
(`browser` | `phone`) and the same endpoint serves ElevenLabs' native Twilio integration, so
it's a config swap, not a redesign.

---

## Observability & evaluation

**Q: What does a LangFuse trace show you?**
Every graph node, the prompt and model, each tool call with args and result, tokens, cost,
latency. Tagged (`maya` + `voice-turn` / `post-call-summary` / `analytics-agent`), grouped by
call session, `user_id = patient:{id}` only after verification so anonymous callers stay
anonymous. Guard-blocked turns are visible as traces that never reached the model.
→ `graph.py` (handler + config), `summarizer.py`, `analytics.py`

**Q: How do logs correlate across services?**
Nginx mints `X-Request-Id`; each FastAPI service's `logging_middleware.py` logs method, path,
status, duration and that id, so one caller action reads across gateway → agent → domain.

**Q: How is the Golden Dataset built and scored?**
28 cases across normal (10) / unsafe (8) / business (4) / unauthorized (3) / invalid (3),
driven through the real `/session → /chat → /wrapup` path with the real OTP flow (the code is
read from the admin inbox endpoint). Assertions on actions — `tools_called`,
`tools_not_called`, `verified`, `guard`, `reply_contains_any` — are deterministic; a Terra
judge grades one wording criterion per case. Went 16 → 19 → 23 → 28 across four runs;
28/28 on EC2.
→ `evals/golden_dataset.json`, `evals/run_eval.py`, `evals/FINDINGS.md`

**Q: What did the eval find that you'd have missed?**
The un-rebookable slot bug and Maya applying the 24 h policy herself, plus behavioural gaps
(not calling `transfer_to_staff`, not refusing claimed authority explicitly, not completing
the action when the caller defers). Lesson: every criterion that specified phrasing
eventually failed a good reply — assert on actions, judge only what must be said.

**Q: What other testing is there?**
Offline pytest suite for the agent (fakes for domain and model in `conftest.py`; runs in CI)
and a 53-check smoke test across the whole stack that asserts the security claims — 403 on
another patient's record, 401 on a forged token, 403 for an unverified voice session, 409 on
double-booking and duplicate feedback.
→ `services/agent/tests/`, `scripts/smoke_test.py`

---

## Deployment & CI/CD

**Q: How does a change reach production?**
Push to main → CI builds the frontend (`tsc -b && vite build`) and runs the agent tests →
deploy job (gated by `DEPLOY_ENABLED`, `concurrency: deploy-production`) opens SSH for the
runner's IP using an IAM user that can only toggle that one SG rule, `git reset --hard` +
`docker compose -f base -f https up -d --build`, closes the rule even on failure, then polls
the three `/healthz` endpoints over TLS.
→ `.github/workflows/ci.yml`

**Q: How do you have HTTPS on a bare IP?**
Let's Encrypt's short-lived IP-address profile via certbot `--ip-address` with an HTTP-01
webroot served by the gateway; a renew script reloads Nginx. TLS is also what lets the browser
open the microphone.
→ `scripts/provision-ip-https.sh`, `scripts/renew-ip-https.sh`, `docker-compose.https.yml`

**Q: What's the fallback if the demo network/voice misbehaves?**
Identical six containers run locally with one command; the text panel and `scripts/talk.py`
drive the same graph and thread; `docker compose down -v && up -d` reseeds.

---

## Honesty questions

**Q: Is this HIPAA-compliant?**
No, and not claimed. Every patient is fictional; OTP delivery is mocked to an admin inbox.
It's a design that *could* be hardened, not a compliant deployment.

**Q: What are the known weaknesses?**
In-memory session store (checkpoints survive a restart; locks and idle timers don't) · web
voice only · regex guards as the outer layer · shared HS256 secret · no migrations · admin
bypass on the 24 h window applies to cancel but not reschedule · one eval case varies with
model nondeterminism · `patients.user_id` isn't unique at the DB level (enforced in the claim
handler).

**Q: What would you build next?**
Phone transport via ElevenLabs' Twilio integration (same graph, `transport='phone'`) · Redis
sessions + a queue for post-call work · Alembic · RS256 · an LLM-judge guard behind the regex
layer · chunking + HNSW · a real EHR adapter behind the domain API · waitlist and outbound
reminders.

**Q: You used AI coding tools — can you explain any file?**
Yes; the brief permits it, and I can walk through any layer — the graph, the tools, the
principal resolver, the nginx config, the CI file. The Jira board and commit history show the
work landing incrementally.

---

## Quick numbers to have ready

- 6 containers · 3 FastAPI services · 1 Nginx gateway · 1 Postgres (pgvector) · ~12.5k LOC
- 2 LangGraph StateGraphs + 1 summariser · 11 tools · 5 input guard kinds + 1 output guard
- 12 tables (10 domain + users + checkpoints) · 15 FAQ docs · ~760 seeded slots
- 28 Golden Dataset cases (28/28 on EC2) · 53 smoke checks · 5 pytest files (~1.1k lines)
- Median voice turn 1.73 s · ~$0.0005 per turn · guard-blocked turn ~1.2 s with no model call
- 12 epics · 47 tickets · 45 done · solo
