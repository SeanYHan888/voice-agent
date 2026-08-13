"""Agent service skeleton — Day 2 replaces the placeholder with the LangGraph workflow
behind an OpenAI-compatible chat-completions endpoint for ElevenLabs."""
from fastapi import FastAPI

app = FastAPI(title="agent-service")


@app.get("/healthz")
def healthz():
    return {"ok": True, "service": "agent"}
