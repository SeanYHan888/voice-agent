# Maya — AI patient access agent

An AI voice agent that answers a dermatology clinic's phone line: schedules appointments,
answers clinic questions, and knows when to stop and fetch a human. Modeled on
[Assort Health](https://www.assorthealth.com/), built against a mock clinic with no real
patient data.

Final project for the Beacon Fire June Python GenAI course. Design and rationale live in
[docs/SPEC.md](docs/SPEC.md); the vocabulary in [CONTEXT.md](CONTEXT.md); decisions in
[docs/adr](docs/adr).

## Running it

You need Docker, and a `.env` (copy `.env.example`). The OpenAI key is required; LangFuse
keys enable tracing; ElevenLabs is only needed for voice.

```bash
docker compose up -d --build
```

The app is at http://localhost. First run seeds the mock clinic: 4 providers, two weeks of
appointment slots, 20 fictional patients, and the FAQ corpus.

Sign in as the admin with the `ADMIN_EMAIL` / `ADMIN_PASSWORD` from your `.env`. For the
patient side, register any account and link it to a seeded record — for example
`+15550100101` with date of birth `1991-03-14`.

## Checking it works

```bash
python3 scripts/smoke_test.py      # 53 checks: business rules and access control
python3 evals/run_eval.py          # 28-case Golden Dataset against the live agent
python3 scripts/talk.py            # talk to Maya in the terminal
```

What testing found, including two bugs it caught: [evals/FINDINGS.md](evals/FINDINGS.md).

## Dependencies

Each Python service owns a `pyproject.toml` and a `uv.lock`; the Docker images install
from the lockfile with `uv sync --locked`, so what runs is exactly what was tested. To
add or bump a dependency, edit the service's `pyproject.toml` and re-lock:

```bash
cd services/agent && uv lock
```

The host-side scripts (`scripts/`, `evals/`) are stdlib-only on purpose — nothing to
install to run them. `mise install` gives you matching `python`, `node`, and `uv`.

## How it fits together

```
browser ──► gateway (nginx) ──┬──► auth-service      JWT, roles
                              ├──► domain-service    patients, slots, appointments,
                              │                      calls, feedback, staff queue
                              └──► agent-service     LangGraph workflows
                                        │
ElevenLabs ─(custom LLM)───────────────►┤
                                        └──► OpenAI · LangFuse · Postgres+pgvector
```

Three LangGraph workflows run in the agent service:

- **Maya** — the conversation. Guard → reason ⇄ tools → guard, checkpointed per call.
- **Post-call summary** — writes each call's summary, intent, and sentiment once it ends.
- **Analytics** — an admin's plain-English question becomes guarded, read-only SQL.

## Two ideas worth knowing before reading the code

**Identity is not something the model decides.** Maya's tools take no patient id. It lives
in the call session server-side, set only by completing verification, and travels to the
domain service as a signed claim. A caller who talks Maya into anything still cannot reach
another patient's records, because the refusal happens below the conversation. See
[services/agent/app/tools.py](services/agent/app/tools.py) and
[services/domain/app/auth.py](services/domain/app/auth.py).

**Business rules live on the server, not in the prompt.** Cancelling within 24 hours of a
visit doesn't execute — it becomes an approval task for staff, and Maya is told to say so.
Early on she read the policy out of the FAQ corpus and reasoned about it herself, which
produced confident wrong answers; the fix was making the tool the only authority. See
[services/domain/app/routers/scheduling.py](services/domain/app/routers/scheduling.py).

## Where things are

| Path | What's there |
|---|---|
| `services/agent` | LangGraph workflows, tools, guardrails, ElevenLabs bridge |
| `services/domain` | Business data and rules, FAQ retrieval, read-only query surface |
| `services/auth` | Registration, login, JWT |
| `frontend` | React + TypeScript + shadcn/ui |
| `evals` | Golden Dataset, runner, findings |
| `scripts` | Smoke test, terminal chat, Jira sync |
| `docs` | Spec, ADRs, setup and demo guides |
