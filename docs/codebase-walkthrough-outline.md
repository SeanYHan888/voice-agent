# Voice Agent Codebase Walkthrough

This roadmap teaches the repository progressively, from the business problem to production architecture and interview-depth tradeoffs. Do not read the entire repository before starting.

## How to use this walkthrough

For each lesson:

1. Define the concept in plain English.
2. Read no more than two to four relevant files.
3. Trace one real request through the code.
4. Predict what the code will do.
5. Run the relevant code.
6. Debug one part of the flow.
7. Practice one interview explanation.

Recommended progression:

- Lessons 1–3: system foundations
- Lessons 4–6: security and business behavior
- Lessons 7–9: AI and user experience
- Lessons 10–11: testing, debugging, and production

## Lesson 1 — What are we building?

**Goal:** Explain Maya without relying on implementation jargon.

Read:

- `README.md`
- `CONTEXT.md`
- `docs/SPEC.md`

Learn:

- The clinic problem Maya addresses
- Caller versus Patient
- Verification versus Authentication
- Appointment, Slot, Call, Escalation, and Approval Task
- What the project deliberately does not handle

Target explanation:

> Maya helps a dermatology clinic automate common phone calls while escalating decisions that require human judgment.

Interview practice:

- What problem does this project solve?
- Who are its users?
- Why is this an agent rather than a normal CRUD application?

**Next:** Once the problem and vocabulary are clear, inspect how the running services divide responsibility.

## Lesson 2 — See the system running

**Goal:** Understand the containers and services before reading their internals.

Read:

- `docker-compose.yml`
- `gateway/nginx.conf`

Run:

```bash
docker compose ps
docker compose logs --tail=20
```

Learn:

```text
Browser → Gateway → Auth / Agent / Domain → PostgreSQL
```

- `frontend`: browser interface
- `gateway`: public entrance
- `auth`: login and JWTs
- `agent`: conversation and LangGraph
- `domain`: clinic data and rules
- `postgres`: persistence and vector search

Interview practice:

- Why use a gateway?
- Why is only the gateway public?
- Are these fully independent microservices?

Checkpoint: Given `/api/domain/slots`, predict which container receives it.

**Next:** Trace the simplest non-AI request through the running system.

## Lesson 3 — Follow the simplest request

**Goal:** Trace a non-AI request from the browser to the database.

Flow:

```text
GET /api/domain/slots
  → Nginx
  → Domain FastAPI router
  → SQLAlchemy query
  → PostgreSQL
  → JSON response
```

Read:

- `services/domain/app/main.py`
- `services/domain/app/routers/scheduling.py`
- `services/domain/app/models.py`

Run:

```bash
curl http://localhost/api/domain/slots
docker compose logs --since=1m domain
```

Learn:

- FastAPI router registration
- Dependency injection with `Depends`
- SQLAlchemy queries
- Pydantic response models
- Why availability is public

Interview practice:

- How does an HTTP request reach the database?
- Where is input validation performed?
- Why does slot search not require authentication?

**Next:** Add identity to the request path through authentication and authorization.

## Lesson 4 — Authentication and authorization

**Goal:** Understand portal identity and permissions.

Flow:

```text
Email + password
  → Auth service
  → bcrypt verification
  → signed JWT
  → frontend stores token
  → domain service validates token
```

Read:

- `services/auth/app/main.py`
- `services/auth/app/security.py`
- `services/domain/app/auth.py`
- `frontend/src/lib/api.ts`

Learn:

- Authentication: who signed into the portal?
- Authorization: what is that person allowed to do?
- JWT claims
- Patient and Admin roles
- Ownership checks
- `401 Unauthorized` versus `403 Forbidden`

Interview practice:

- Why does the domain service validate the JWT again?
- What happens if someone changes their frontend role?
- Why is frontend route protection insufficient?

**Next:** Compare portal authentication with identity verification during a voice Call.

## Lesson 5 — Voice verification and secure identity

**Goal:** Understand the project's central security design.

Flow:

```text
Anonymous Caller
  → requests verification code
  → reads code back
  → server finds Patient
  → CallSession receives patient_id
  → agent signs session JWT
  → domain service permits patient operations
```

Read:

- `services/agent/app/session.py`
- `services/agent/app/tools.py`
- `services/domain/app/routers/verification.py`
- `services/domain/app/auth.py`

Key idea:

> The model never supplies a patient ID. Identity comes from verified server-side state.

Interview practice:

- Why is the prompt not a security boundary?
- Can prompt injection expose another Patient's Appointment?
- What identity state is lost if the agent container restarts?
- Does that failure happen safely?

**Next:** Use verified identity to enforce scheduling and clinic policies.

## Lesson 6 — Scheduling and business rules

**Goal:** Understand where the clinic's operational rules live.

Read:

- `services/domain/app/routers/scheduling.py`
- `services/domain/app/routers/admin.py`
- `services/domain/app/schemas.py`

Trace:

1. Search available Slots.
2. Book a Slot.
3. Reject double booking.
4. Cancel outside 24 hours.
5. Cancel inside 24 hours.
6. Create an Approval Task.
7. Have an Admin approve it.

Learn:

- Database transactions
- Row locking with `FOR UPDATE`
- Ownership enforcement
- Conflict responses
- Human-in-the-loop workflow

Interview practice:

- How do you prevent two callers from booking the same Slot?
- Why is the 24-hour rule in the domain service rather than the prompt?
- What happens if a reschedule Slot is taken before approval?

**Next:** See how LangGraph decides which protected operation to request.

## Lesson 7 — LangGraph: the agent's brain

**Goal:** Understand one conversation turn.

Read:

- `services/agent/app/main.py`
- `services/agent/app/graph.py`
- `services/agent/app/prompts.py`
- `services/agent/app/tools.py`

Graph:

```text
START
  ↓
input_guard
  ↓
reason ⇄ tools
  ↓
output_guard
  ↓
END
```

Learn:

- Graph state
- Nodes and conditional edges
- LLM tool selection
- Tool execution loops
- Postgres checkpointing
- Conversation thread IDs
- Why evaluation captures tool calls

Run:

```bash
python3 scripts/talk.py
docker compose logs -f agent domain
```

Interview practice:

- Why use LangGraph instead of calling the model once?
- How does conversation memory work?
- What happens when the model calls multiple tools?
- What happens if OpenAI fails?

**Next:** Examine the deterministic safety layers surrounding the model.

## Lesson 8 — Guardrails, FAQ retrieval, and escalation

**Goal:** Separate deterministic safety from probabilistic model behavior.

Read:

- `services/agent/app/guardrails.py`
- `services/domain/app/faq.py`
- `services/agent/app/tools.py`

Learn:

- Input guard versus output guard
- Emergency and medical-advice detection
- Prompt-injection detection
- FAQ retrieval with pgvector
- Retrieved-document sanitization
- Human escalation

Interview practice:

- Are regex guardrails sufficient?
- What happens when retrieval returns nothing?
- How does the system defend against a poisoned FAQ document?
- Which safety checks are deterministic?

**Next:** Connect the browser and voice interfaces to the same agent workflow.

## Lesson 9 — Frontend and voice integration

**Goal:** Trace text and voice into the same agent.

Read:

- `frontend/src/App.tsx`
- `frontend/src/components/MayaPanel.tsx`
- `frontend/src/lib/api.ts`
- `docs/adr/0001-elevenlabs-voice-shell-langgraph-brain.md`

Compare:

```text
Text:
React → POST /agent/chat → LangGraph

Voice:
ElevenLabs → /agent/v1/chat/completions → LangGraph
```

Learn:

- React state and API calls
- Session correlation
- ElevenLabs as the audio shell
- LangGraph as the reasoning brain
- Vite build-time environment variables

Interview practice:

- Why not let ElevenLabs own the entire agent?
- Why not build the audio pipeline manually?
- How do text and voice share conversation identity?

**Next:** Prove the behavior through deterministic tests and agent evaluations.

## Lesson 10 — Testing and live debugging

**Goal:** Be able to demonstrate that the project works and diagnose failures.

Read:

- `scripts/smoke_test.py`
- `evals/run_eval.py`
- `evals/golden_dataset.json`
- `evals/FINDINGS.md`

Testing levels:

```text
Unit tests
  ↓
API integration tests
  ↓
Agent Golden Dataset
  ↓
Browser/voice end-to-end test
```

Hands-on sequence:

1. Write a guardrail unit test.
2. Make it fail intentionally.
3. Read the traceback.
4. Fix it.
5. Run the smoke suite.
6. Run one Golden Dataset case.
7. Correlate agent logs, domain logs, database state, and LangFuse.

Interview practice:

- How do you test nondeterministic LLM behavior?
- Which assertions should be deterministic?
- Why assert on tool calls instead of exact wording?
- What important tests are still missing?

**Next:** Move from local correctness to deployment and production tradeoffs.

## Lesson 11 — Deployment and architectural tradeoffs

**Goal:** Explain how the local system becomes a production service.

Read:

- `docs/deploy-ec2.md`
- `docker-compose.https.yml`
- `.github/workflows/deploy.yml`

Learn:

- Docker image construction
- EC2 deployment
- HTTPS requirements for voice
- Secrets and build-time variables
- Health checks
- Current scaling limitations

Interview practice:

- What would you change before production?
- How would you run multiple agent replicas?
- How would you migrate the database safely?
- How would you improve observability and request tracing?

**Next:** Rehearse the project introduction, one complete request trace, the security model, test evidence, and production improvements as a single interview narrative.

## Final practice order

1. Give the 30-second problem statement.
2. Define the domain actors and identity terms.
3. Draw the service boundary diagram from memory.
4. Trace public Slot search.
5. Trace portal authentication.
6. Trace voice Verification and booking.
7. Explain the LangGraph loop.
8. Explain deterministic versus LLM-based testing.
9. Name three current limitations and sensible production improvements.
