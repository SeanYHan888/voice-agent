# Technical map and learner-led build

## First, inspect the actual starting point

At local commit `86790fe`, this repository already has an ElevenLabs custom-LLM endpoint in [`services/agent/app/main.py`](../../services/agent/app/main.py), a LangGraph workflow in [`graph.py`](../../services/agent/app/graph.py), session identity in [`session.py`](../../services/agent/app/session.py), and domain-authorized tools in [`tools.py`](../../services/agent/app/tools.py). [`scheduling.py`](../../services/domain/app/routers/scheduling.py) validates appointment ownership and policy, locks a slot, and returns the database result. [`test_voice_adapter.py`](../../services/agent/tests/test_voice_adapter.py) and [`test_session_lifecycle.py`](../../services/agent/tests/test_session_lifecycle.py) exercise parts of the existing transport and state logic. The [architecture decision](../adr/0001-elevenlabs-voice-shell-langgraph-brain.md) deliberately chose ElevenLabs for the course sprint; the [spec](../SPEC.md) says inbound phone calling was deferred.

For the new Twilio path, the gaps are concrete:

- There is no incoming Twilio Voice webhook, ConversationRelay TwiML, or ConversationRelay WebSocket handler.
- The existing `/v1/chat/completions` path returns an SSE response **after** `run_turn` finishes; this is a valid ElevenLabs-facing shape but does not demonstrate first-token streaming from the model or Twilio `text` messages.
- The current per-session lock serializes turns. It avoids simultaneous checkpoint writes, but an interrupt cannot cancel a generation that is waiting inside the old turn merely by taking that lock.
- The domain client converts HTTP transport failures to a generic scheduling error. The reschedule endpoint has no durable operation ID or read-by-operation reconciliation contract. The current escalation creates an Admin task; it is not a live Twilio call transfer.
- Existing session identity/checkpoints are useful to reuse, but a ConversationRelay socket needs its own `callSid`, `sessionId`, turn generation, task ownership, disconnect, and transfer lifecycle.
- The existing [`prompts.py`](../../services/agent/app/prompts.py) asks for short, relevant spoken answers, and [`guardrails.py`](../../services/agent/app/guardrails.py) checks input and completed output. A Twilio streaming adapter still needs an explicit **before-speech** check: once a text chunk is spoken, a later output guard cannot retract it. The current guards also do not prove every unsupported claim or privacy leak will be caught.

These are observations about this version, not criticisms of the completed course scope. This repository is the demo/MVP used to learn the Twilio Voice AI application path. Keep the existing ElevenLabs demo working while building the Twilio adapter as an additional transport. The clinic data is synthetic; no real customer or production outcome is implied.

**Baseline check performed October 14, 2026:** `uv run --offline pytest -q` in `services/agent` passed **142 tests**. It emitted two FastAPI startup deprecation warnings. This checks the current agent service; it does not test the proposed Twilio path.

## Technical categories to dive into

| Category | Questions it answers | Main repository anchors | Artifact to produce |
|---|---|---|---|
| 1. Voice entry and protocol | Call walkthrough; ConversationRelay vs Media Streams | `services/agent/app/main.py`, `gateway/`, new Twilio adapter | Validated webhook, TwiML, `setup`/`prompt`/`text` replay |
| 2. Conversation and speech state | Interruption; what was heard | `graph.py`, `session.py`, new turn controller | Epoch and playback ledger; late-token test |
| 3. LLM and tools | Call walkthrough; why model cannot book | `graph.py`, `tools.py`, `domain_client.py` | Tool contract and authorized execution trace |
| 4. Scheduling transactions | Interrupt during tool; timeout and retry | `scheduling.py`, models and schemas | Operation ledger, authoritative status query, timeout replay |
| 5. Multi-call ownership and recovery | Simultaneous calls; socket/server failure | `session.py`, `graph.py`, new socket lifecycle | Isolation, disconnect, restart, and cleanup tests |
| 6. Escalation and agent experience | When/how transfer; compound race | `calls.py`, Admin queue, new handoff controller | Transfer state machine and refreshed agent context |
| 7. Security and privacy | Secure system | `auth.py`, verification routes, new webhook/socket validation | Boundary review and negative tests |
| 8. Latency, quality, and cost | Where latency lives; success | `evals/`, `scripts/smoke_test.py`, new call telemetry | Stage timings, first-audio trace, cost/correctness report |
| 9. Error handling and fallback | Dependency failures; what caller hears next | `domain_client.py`, new adapter, transfer controller | Failure matrix and deterministic caller messages |
| 10. Answer relevance and speech safety | Avoid unnecessary, unsupported, or private information | `prompts.py`, `guardrails.py`, `evals/` | Allowed-intent/response contract and before-speech tests |
| 11. Related questions and follow-ups | How the AI answers FAQ, availability, and appointment-status questions | `tools.py`, `faq.py`, `graph.py`, `prompts.py` | Two-turn FAQ trace, verified status read, and no-match fallback |

Use [Twilio's WebSocket message reference](https://www.twilio.com/docs/voice/conversationrelay/websocket-messages) for actual event names and fields. Do not reuse the ElevenLabs payload format for ConversationRelay.

## Roadmap: one capability at a time

| Step | Capability | Observable deliverable | Completion check |
|---|---|---|---|
| **1 — active** | Trace the current app and define the Twilio event contract | A written trace of one Maya reschedule and a Twilio call/event diagram | Can point to the code owner of identity, tool validation, commit, speech, and escalation; protocol fixtures match current docs |
| 2 | Accept an inbound Twilio call | Voice webhook returns `<Connect><ConversationRelay>` TwiML; local socket accepts `setup` | Fake signed webhook and WebSocket replay pass; invalid signatures fail |
| 3 | Make the caller hear a bounded answer | Final `prompt` invokes the existing agent; validated current-turn clauses flow back as `text` | Replay proves ordering, terminal `last`, short relevant FAQ answers and follow-ups, a no-match fallback, and no unvalidated booking confirmation; live test hears a greeting and FAQ answer |
| 4 | Handle interruption | Per-call generation/task controller and heard-text ledger | Barge-in stops old output; late tokens never reach caller; history reflects played words |
| 5 | Make scheduling reliable | Authorized command with stable operation ID and authoritative reconciliation | Timeout with late success causes one logical change and a truthful outcome; duplicate and concurrent requests tested |
| 6 | Transfer to a person | `end`/action callback route and agent-facing state | Caller reaches human or explicit fallback; agent sees refreshed verified context and booking status |
| 7 | Survive failures securely | Failure matrix, disconnect cleanup, replacement-session/fallback path, security review | Model/tool/socket/transfer failures yield truthful caller messages; no cross-call leakage; logs and transcripts have bounded access |
| 8 | Run an end-to-end MVP demo | Synthetic calls, fault injection, metrics and cost report | Interview demo walks webhook → speech → tool → interruption → transfer, with measured demo timings and no invented production claims |

Each later step can be broken into a TODO ladder when you reach it. A live phone test requires your own Twilio account, reachable WSS endpoint, and any charges associated with calls and speech. Keep the offline replay as the default learning path; do not configure or spend on a live route merely to validate basic logic.

## Step 1: active TODO ladder

This step is deliberately a **trace and contract exercise**. It changes no application behavior. Keep the notes in this folder so the next step can use them.

```text
TODO(Step 1.1): Trace one existing reschedule from the user message through the graph, tool, domain client, scheduling endpoint, and response.
Why: Know which layer owns each decision before adding a new transport.
Hint: Start at POST /chat or /v1/chat/completions in main.py; follow reschedule_appointment in tools.py.
Done when: Your trace names the verified identity, policy check, database commit, response, and current timeout behavior.

TODO(Step 1.2): Draw the proposed Twilio call timeline using documented setup, prompt, interrupt, text, and end messages.
Hint: Keep CallSid, ConversationRelay sessionId, turn generation, and booking operation ID distinct.
Done when: Every arrow says who sends it and which identifier it carries.

TODO(Step 1.3): Write three synthetic event sequences: happy path, interruption during speech, and timeout + interruption + transfer + late success.
Hint: Put absolute ordering in each trace; identify the moment the caller could have heard a statement.
Done when: A reader can predict the caller's audio, booking state, and agent view after every event.

TODO(Step 1.4): Run the existing offline agent tests and record the baseline without changing code.
Hint: Use `uv run pytest` from services/agent. A missing dependency or environment requirement is a baseline result, not a reason to guess success.
Done when: The note records the exact check and result, including any blocker.

TODO(Step 1.5): Explain ConversationRelay versus Media Streams and name one requirement that would change the decision.
Done when: You can answer the choice in under 60 seconds and identify which audio responsibilities move to your app with Media Streams.

TODO(Step 1.6): Define the allowed answer scope and a compact spoken-response contract for this demo.
Hint: Separate a factual FAQ answer, a booking confirmation, an unsupported question, and an explicit request for a person.
Done when: Each case says what evidence permits speech, what may not be volunteered, and when transfer wins over more AI questions.

TODO(Step 1.7): Add a failure table to the trace for unclear speech, model failure, missing FAQ evidence, booking rejection, booking timeout, socket loss, and failed transfer.
Done when: Each row distinguishes known failure from unknown business outcome and states exactly what the caller hears and what an agent sees.

TODO(Step 1.8): Trace two related caller questions through the existing FAQ tool and conversation history, then contrast them with a personal appointment-status question.
Hint: Use “Do you have parking?” followed by “Is it free?”; compare with “What time is my appointment?”
Done when: The note identifies which answer needs an approved FAQ entry, which needs verified identity plus a fresh scheduling read, and what the caller hears when no reliable FAQ entry exists.
```

The [official research](official-research.md) is a source sheet, not a substitute for reading the current protocol schema while implementing. Use the [interview practice](interview-practice.md) as a target for the final teach-back. Once Step 1 is complete, the next workshop action is to scaffold only Step 2's webhook and socket contracts.
