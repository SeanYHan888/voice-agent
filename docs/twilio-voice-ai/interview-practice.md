# Interview practice: answer from evidence and a tested design

These are **practice answers for the Twilio Voice AI demo/MVP in [the story](project-story.md)**. Say “I would build” for a proposed step and “I built and tested in my demo” only after that step works in this repository. Twilio behavior is linked to [official research](official-research.md); booking and agent workflow are application design, not Twilio platform features.

## 1. “Walk me through a call from the incoming webhook to the caller hearing a response.”

Twilio sends the configured Voice webhook to our server. We validate its signature and return TwiML with `<Connect><ConversationRelay url="wss://...">`. At the WebSocket handshake we validate Twilio again; `setup` gives us `callSid` and ConversationRelay `sessionId`. ConversationRelay handles speech recognition and sends a `prompt` with the caller's transcribed words; a final `last: true` prompt is the turn boundary. Our per-call controller sends the text to the LLM service. If the model requests a booking tool, our backend checks verified identity, appointment ownership, slot and policy, then calls the booking service and feeds its actual result back to the model. We check each proposed spoken clause against the allowed scope and current authoritative state **before** sending a `text` message with `token`; the final message has `last: true`. Twilio synthesizes the released text and the caller hears it. A slow tool may get a short truthful acknowledgment, but booking confirmation waits for the authoritative result. [TwiML and ConversationRelay](https://www.twilio.com/docs/voice/twiml/connect/conversationrelay); [WebSocket messages](https://www.twilio.com/docs/voice/conversationrelay/websocket-messages).

## 2. “Why did you choose ConversationRelay instead of Media Streams?”

For an appointment agent, the hard differentiator is correct business action and escalation. ConversationRelay supplies call speech recognition, synthesis, and conversational pacing and gives us structured text events, so our team can focus on authorization, tool reliability, and caller experience. Media Streams gives raw audio access and bidirectional media control, which is useful for a custom STT/TTS stack or speech-to-speech model; it means we own audio encoding, buffering, turn-taking, interruption, and additional latency paths. I would revisit the choice if raw audio features or a provider requirement justified that cost. [ConversationRelay](https://www.twilio.com/docs/voice/conversationrelay); [Media Streams](https://www.twilio.com/docs/voice/media-streams).

## 3. “How do you handle a caller interrupting the AI mid-sentence?”

Twilio sends an `interrupt` with `utteranceUntilInterrupt`, indicating the portion played before interruption. I advance the call's generation epoch, cancel the old model stream where possible, and reject any later tokens from that epoch. I record what was heard using the interrupt boundary and, when configured, playback events; the full text the model generated is not automatically conversation history. The new caller prompt starts a new turn from the heard context. I test late-token races and the ordering where `interrupt` arrives before the next final prompt. [WebSocket messages](https://www.twilio.com/docs/voice/conversationrelay/websocket-messages).

## 4. “What happens if the caller interrupts while a scheduling tool is running?”

I stop obsolete *speech*, not the business transaction. If the tool call has already reached the booking service, cancellation of our waiting task cannot prove the booking did not change. The operation keeps a stable ID and durable outcome record. I reconcile it independently, suppress the old conversational reply, and use the confirmed outcome in the new turn or human handoff. If the result remains unknown, I tell the caller that it is being checked. This is an application rule, not a ConversationRelay rollback feature.

## 5. “The scheduling API times out after a reschedule request. Do you retry?”

Not as a new operation. The timeout could mean the request never arrived, or it could mean the booking committed and its response was lost. I mark the operation `unknown`, retain the same operation ID and request parameters, and query the authoritative booking state. A retry is safe only if the scheduling API offers a documented deduplication contract for that same ID, or after reconciliation proves no effect and the operation is still allowed. Without either, I escalate for review. I never report success or failure from the timeout alone. The current toy reschedule route needs this contract added; its existing row lock protects slot contention but does not answer this ambiguity.

## 6. “How do you keep simultaneous calls and histories separate?”

`callSid` identifies the call; `sessionId` identifies a ConversationRelay connection, which may change if a session is replaced. I keep call state keyed by the call, socket state by the session, and each model stream by `(call, turn epoch)`. Each tool command has its own operation ID. The existing LangGraph checkpoint uses a per-session thread ID; the Twilio adapter must map that deliberately to the stable call identity and must never use a shared placeholder. On disconnect, I cancel transient speech tasks and release sockets, while keeping durable booking status for reconciliation and retention rules. Tests interleave two synthetic calls and assert that neither tokens nor history cross. [WebSocket messages](https://www.twilio.com/docs/voice/conversationrelay/websocket-messages).

## 7. “Why can’t the LLM update appointments directly?”

The model is an untrusted planner: it can misunderstand speech, be prompted by a malicious caller, or select an invalid slot. The backend verifies the caller through a separate mechanism, checks appointment ownership and business policy, validates structured arguments, enforces the booking system's concurrency rules, and returns its actual result. The existing toy app already puts identity below the model and policy in the domain service; the Twilio version must preserve those boundaries. Caller ID or a persuasive prompt is not authorization.

## 8. “Where is the latency, and how would you reduce it?”

I time from the caller's end of speech to first **audible** response and then separate end-of-speech detection, STT finalization, WebSocket/network transit, model first token, any tool round trip, and TTS start/playback. Twilio Conversation Relay Insights reports network RTT, STT, application time to first token, and TTS playback stages, with documented measurement limits. I improve the dominant measured stage: streaming text earlier, trimming prompt work, using a faster model where quality holds, reducing unnecessary tool calls, or moving an acknowledgment before a slow tool. I never let a latency optimization claim a booking succeeded before confirmation. [Conversation Relay Insights](https://www.twilio.com/docs/voice/voice-insights/conversation-relay-summary).

## 9. “What happens if the WebSocket or your server fails during a call?”

I do not promise transparent reconnect: Twilio says it does not automatically reconnect an unexpectedly lost ConversationRelay WebSocket. I treat it as a failed session, clean up its tasks, retain durable booking operations, and use the `<Connect>` action path where the call is still routable to offer a replacement session or human fallback. The exact caller behavior must be tested with the Twilio configuration because a failed call and a failed relay session are different outcomes. A replacement session is linked to the same `callSid`, but gets a new connection identity; it reloads verified state only from trusted persisted records and checks any in-flight booking before speaking. [WebSocket failures and reconnection](https://www.twilio.com/docs/voice/conversationrelay/websocket-messages); [TwiML action callback](https://www.twilio.com/docs/voice/twiml/connect/conversationrelay).

## 10. “When and how do you transfer to a human?”

Escalate on caller request, identity or policy failure, repeated recognition failure, unresolved booking outcome, distress, or a time budget exceeded. The app stops new AI speech, records a reason and a small verified handoff record, then sends ConversationRelay `type: "end"` with a non-sensitive `handoffData` reference. The `<Connect>` action callback returns TwiML to dial or queue the agent. The human UI loads and refreshes the authoritative handoff record: identity status, intent, last words confirmed heard, booking operation and its latest outcome. `HandoffData` is a callback string and can be stale by the time the agent answers, so it should carry a reference, not be treated as the live database. [WebSocket handoff](https://www.twilio.com/docs/voice/conversationrelay/websocket-messages); [TwiML action](https://www.twilio.com/docs/voice/twiml/connect/conversationrelay).

## 11. “How do you secure the system?”

Validate Twilio's signature on the Voice webhook, action callback, and initial WebSocket request, using the exact public URL and the official SDK approach. Authenticate the **caller separately** before access to appointment data. Authorize every tool action server-side and restrict the agent to approved operations. Keep Twilio and model secrets in secret storage; avoid putting them in prompts or logs. Limit transcript collection, redact logs, set retention and role-based access, and test unauthorized appointment IDs and forged webhooks. This mock repo uses synthetic clinic data; it does not prove regulatory compliance. [Twilio webhook security](https://www.twilio.com/docs/usage/webhooks/webhooks-security); [ConversationRelay onboarding](https://www.twilio.com/docs/voice/conversationrelay/onboarding).

## 12. “How did you test and measure success?”

I would replay exact protocol fixtures offline, then test a live synthetic call and inject interruptions, stale model tokens, concurrent calls, booking timeouts with late success, duplicate requests, transfer races, WebSocket loss, model failure, missing FAQ evidence, and failed transfer. I would audit the authoritative appointment after each case and inspect what the caller heard and the agent saw. I would also test off-topic requests, prompt injection, unsupported factual claims, privacy leakage, overly long answers, and false positives where a valid short answer was blocked. Pilot measures are correctly completed eligible requests, incorrect/duplicate bookings, unresolved outcomes, completed calls, transfer reasons, abandonment/repeat calls, first-audible-response latency by stage, unsupported-answer rate, and cost per correctly completed request. A deflected call is not success if the booking is wrong. The practice repo can report its own test counts and traces after they run; no production improvement number is claimed here.

## 13. “What if the model, speech, lookup, or transfer path fails?”

I classify the failure before choosing words. If speech is unclear, I ask for one detail again and perform no mutation. If the model fails or a factual lookup has no relevant source, I use a short approved fallback or offer a person instead of improvising. A booking rejection is a known business result and can be explained with an allowed alternative; a booking timeout is an **unknown outcome** and needs reconciliation under the same operation ID. A lost ConversationRelay socket does not automatically reconnect, so I clean up transient tasks and use the tested call fallback if the call remains routable. If human routing fails, I offer an approved callback path and retain the booking status for the agent. Each path gets an error category and trace ID, while the caller hears only the status and next step that matter. [ConversationRelay failure behavior](https://www.twilio.com/docs/voice/conversationrelay/websocket-messages).

## 14. “How do you stop the AI from giving unnecessary or unverified information?”

I define an allowed-intent and response contract: answer only the caller's question, usually in one or two spoken sentences; ask one necessary follow-up; never volunteer internal IDs, private details, model reasoning, or unrelated facts. A public FAQ answer needs an approved source; a booking confirmation needs an authoritative booking result; a person request triggers handoff without more persuasion. The input guard catches out-of-scope or instruction-changing requests, but the decisive boundaries are server-side tool permissions and a **before-speech** output gate. In a streaming system I validate a short clause before sending it to Twilio; for high-risk statements I use a deterministic template filled from a confirmed result. I test both bad answers that slip through and valid answers blocked by the guard. The existing Maya repo has concise prompt rules and completed-output checks; the Twilio adapter's streaming gate remains a proposed exercise.

## 15. “The caller asks a question related to the service. How does the AI answer and handle a follow-up?”

ConversationRelay sends the transcribed question as a `prompt`; the application keeps it with that call's history. The agent classifies whether it needs approved FAQ content, live availability, or a verified appointment read. It calls the appropriate tool, then gives a short spoken answer grounded in the returned result. For “Do you have parking?” the synthetic FAQ supports “Yes, parking is free in the attached garage.” If the caller follows with “Is it free?”, history resolves “it” to parking; the agent answers “Yes” without repeating the entire policy. If they ask “What time is my appointment?”, the agent verifies identity and reads current state rather than answering from memory. With no relevant source or unclear speech, it says what it cannot confirm and asks one clarifying question or offers a human. The existing Maya repo has the FAQ, scheduling tools, and conversation workflow; the ConversationRelay speech path is still a proposed extension. [ConversationRelay prompt messages](https://www.twilio.com/docs/voice/conversationrelay/websocket-messages).

## Main drill: timeout + interruption + late success during transfer

**Question:** “The booking API times out, the caller interrupts, and a success response arrives while you transfer them to an agent. What does each person hear and see?”

| Order | Application state | Caller hears | Human agent sees |
|---|---|---|---|
| 1. Reschedule submitted | One validated operation ID; outcome pending | “I’m checking that change.” No confirmation. | No handoff yet. |
| 2. API deadline passes | Outcome `unknown`; reconcile via operation ID/current appointment | No “failed” or “done” claim. | If handoff starts now: `unknown`, requested old/new slot, verification status. |
| 3. Caller interrupts and asks for human | Old generation epoch invalid; old tokens blocked; heard-text boundary recorded | Old sentence stops; a short deterministic “I’ll connect you and have them check the change.” | Transfer reason and last confirmed spoken status. |
| 4. Success response arrives during transfer | Match to same operation; verify or reconcile against booking authority; atomically update durable handoff status | No stale AI success sentence plays after handoff begins. | Refresh on answer: `confirmed`, new slot and timestamp, plus “caller has not heard confirmation.” |
| 5. Agent answers | AI turn remains closed; booking status remains durable | Agent confirms the actual new appointment. | Agent can explain it without resubmitting the change. |

If the late response cannot be verified, the agent instead sees `unknown` and checks the booking system before promising or retrying. If the transfer itself fails while the call remains active, the callback follows a tested fallback path; the booking reconciliation continues. The invariant is that **speech cancellation does not cancel a transaction**, and **a late transaction result does not revive a closed AI conversation**.

### Practice prompt

Explain the table aloud in 90 seconds, then answer these follow-ups without reading:

1. Which identifier deduplicates the booking, and which identifier isolates the call?
2. What if success arrives after the human starts speaking?
3. What if the caller heard only half of “Your appointment is moved...” before interruption?
4. What if the booking system offers no idempotency key or status lookup?

For follow-up 2, the agent UI must refresh or receive a status update and the human conveys the confirmed result. For 3, the caller has not heard a reliable confirmation; use Twilio's interruption boundary/playback evidence and have the human repeat the exact verified appointment. For 4, hold the result as unknown and route to a human to inspect the authoritative record; do not blindly retry.
