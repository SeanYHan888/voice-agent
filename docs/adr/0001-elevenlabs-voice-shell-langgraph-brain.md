# ElevenLabs is the voice shell; LangGraph is the brain

ElevenLabs Agents handles the real-time audio problem (STT, TTS, turn-taking, barge-in, and native Twilio telephony), but its LLM is pointed at our Agent Service's OpenAI-compatible endpoint, so every conversational turn runs through our LangGraph workflow — where tools, guardrails, access control, and LangFuse tracing live. The agent's intelligence is ours; ElevenLabs only carries the audio.

## Considered Options

- **ElevenLabs fully managed** (its built-in LLM + webhook tools calling our APIs): least work, but the reasoning lives in ElevenLabs — LangGraph would be sidelined, failing the course's central requirement that the agent workflow be the heart of the system.
- **Raw pipeline** (Twilio Media Streams → STT → LangGraph → ElevenLabs TTS): maximum control and credit for depth, but hand-building turn-taking, interruption handling, and latency tuning is infeasible in a one-week solo sprint.

## Consequences

- The same LangGraph agent serves both transports (browser widget and phone) — the demo fallback comes for free.
- Voice-turn latency budget constrains the model choice for conversational turns (fast tier, minimal reasoning).
- If ElevenLabs' custom-LLM contract changes, only the Agent Service's endpoint adapter is affected.
