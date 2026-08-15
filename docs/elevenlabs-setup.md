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
| **System prompt** | leave empty — ours is applied server-side, inside the graph |

Leave the ElevenLabs tool configuration empty too. Tools belong to the LangGraph workflow;
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
gets a `session_id`. That id reaches the custom-LLM endpoint through the widget's
`user-id`. The service also accepts `X-Session-Id`, `user`, `user_id`, `session_id`,
`conversation_id`, metadata, and ElevenLabs' extra-body session field so the browser and
voice paths converge on the same server-side session.

That id is the only thing tying a voice turn to a verified patient. The patient id itself
lives server-side in the session store and is never accepted from the request body, so a
caller cannot claim to be someone else by editing what the voice platform sends.

## If something doesn't work

- **ElevenLabs reports the LLM is unreachable** — the Server URL must end in `/v1` and be
  publicly resolvable over trusted HTTPS. Check the protected probe from outside your
  network:

  ```bash
  curl -H "Authorization: Bearer $ELEVENLABS_LLM_API_KEY" \
    https://YOUR-HOST/api/agent/v1/models
  ```
- **Maya answers, but forgets everything between turns** — the session id isn't arriving.
  Check `docker compose logs agent` for a new session per turn, and confirm the widget is
  passing the id it was given.
- **Long silences before she speaks** — check the LangFuse trace for that turn. Tool calls
  add a round trip; two chained tool calls in one turn is the usual cause.
- **She talks over the caller** — that's ElevenLabs' turn-taking, not ours; adjust the
  interruption sensitivity in their dashboard.
