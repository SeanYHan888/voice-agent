# Connecting ElevenLabs to Maya

Everything Maya decides happens in our LangGraph workflow. ElevenLabs only carries the
audio: speech in, speech out, turn-taking. It reaches our brain through an
OpenAI-compatible endpoint the agent service already exposes.

Two things must be true before this works:

1. **The agent service is reachable over public HTTPS.** ElevenLabs calls our endpoint
   from their servers, so `localhost` is not enough. Use the EC2 deployment, or `ngrok
   http 80` while developing.
2. **You have an ElevenLabs agent created** in their dashboard.

## 1. Expose the endpoint

Local development:

```bash
ngrok http 80
```

Note the HTTPS URL it prints — for example `https://a1b2c3.ngrok-free.app`. Our endpoint
is that URL plus `/api/agent/v1`. Confirm it answers:

```bash
curl -H "Authorization: Bearer $ELEVENLABS_LLM_API_KEY" \
  https://YOUR-HOST/api/agent/v1/models
```

You should see `gpt-5.6-luna` listed. That endpoint is what ElevenLabs probes when
validating a custom LLM.

## 2. Configure the agent

In the ElevenLabs dashboard, create a Conversational AI agent and set:

| Setting | Value |
|---|---|
| **LLM** | Custom LLM |
| **Server URL** | `https://YOUR-HOST/api/agent/v1` |
| **Model ID** | `gpt-5.6-luna` |
| **API key** | the same random value stored as `ELEVENLABS_LLM_API_KEY` in the app's `.env` |
| **First message** | `Thanks for calling Assort Dermatology, this is Maya. How can I help you today?` |
| **System prompt** | exactly the two lines below — nothing else. Maya's real prompt is applied server-side, inside the graph |
| **Custom LLM extra body** | on |

System prompt field:

```
session_id={{session_id}}
conversation_id={{system__conversation_id}}
```

Then, under the agent's **Dynamic variables**, add `session_id` with an empty default
so calls that don't come from our widget (the dashboard test console, a phone number)
still start.

Why the odd system prompt: ElevenLabs sends its own system prompt as the first message
of every custom-LLM request, with dynamic variables already substituted. That makes it
the one channel that carries an id from the widget, the test console, and a phone call
alike. Our endpoint reads `session_id=` (the widget's session, which may already be a
logged-in patient) and falls back to `conversation_id=` (ElevenLabs' own id, stable for
the life of one call). Either way, every turn of a call lands in the same LangGraph
thread — which is what keeps memory and verification alive between turns.

Leave the ElevenLabs tool configuration empty. Tools belong to the LangGraph workflow;
if you also define them there, you get two agents fighting over the same conversation.

Pick a warm, natural voice and keep latency settings at their defaults.

## 3. Point the frontend at it

Copy the agent id from the dashboard into `frontend/.env`:

```
VITE_ELEVENLABS_AGENT_ID=your_agent_id_here
```

Rebuild the frontend (`docker compose up -d --build frontend`). The Maya panel then shows
a microphone alongside the text box, both driving the same session.

## How session identity survives the hop

The widget opens a session with our agent service first (`POST /api/agent/session`) and
gets a `session_id`. Just before the widget connects it fires `elevenlabs-convai:call`;
we use that hook to stamp the id on the session config as `userId`, `customLlmExtraBody`,
and the `session_id` dynamic variable, so it reaches our endpoint whichever of those the
platform forwards. The service reads, in order: `X-Session-Id`, `user`/`user_id`,
`session_id` in the extra body or dynamic variables, `session_id=` in the platform's
system prompt, then the ElevenLabs conversation id (`conversation_id=` in the system
prompt or extra body). The browser and voice paths converge on the same server-side
session.

That id is the only thing tying a voice turn to a verified patient. The patient id itself
lives server-side in the session store and is never accepted from the request body, so a
caller cannot claim to be someone else by editing what the voice platform sends.

If a turn arrives with no id at all, the service logs a warning and backfills the graph
from the transcript ElevenLabs sends with each request, so Maya at least remembers what
was said — but verification cannot survive to the next turn in that mode. Treat the
warning as a configuration bug, not a runtime one.

## If something doesn't work

- **ElevenLabs reports the LLM is unreachable** — the Server URL must end in `/v1` and be
  publicly resolvable over trusted HTTPS. Check the protected probe from outside your
  network:

  ```bash
  curl -H "Authorization: Bearer $ELEVENLABS_LLM_API_KEY" \
    https://YOUR-HOST/api/agent/v1/models
  ```
- **Maya answers, but forgets everything between turns** — she asks "are you a new or
  existing patient?", you answer, she says "welcome back, what would you like to do?",
  and round it goes. The session id isn't arriving. Look for `Voice turn arrived without
  any session or conversation id` in `docker compose logs agent`, then check the agent's
  system prompt carries the two marker lines above and that "Custom LLM extra body" is on.
- **Long silences before she speaks** — check the LangFuse trace for that turn. Tool calls
  add a round trip; two chained tool calls in one turn is the usual cause.
- **She talks over the caller** — that's ElevenLabs' turn-taking, not ours; adjust the
  interruption sensitivity in their dashboard.
