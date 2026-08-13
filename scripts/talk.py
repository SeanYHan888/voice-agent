#!/usr/bin/env python3
"""Talk to Maya over the text surface.

    python3 scripts/talk.py                      # interactive
    python3 scripts/talk.py "line one" "line two"  # scripted turns

Same LangGraph workflow the voice widget drives, minus the audio — handy for iterating
on prompts, and the fallback if the demo room's microphone misbehaves.
"""
import json
import sys
import urllib.error
import urllib.request

BASE = "http://localhost/api/agent"


def post(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode(errors='replace')[:800]}", file=sys.stderr)
        raise SystemExit(1)


def main() -> None:
    start = post("/session", {"transport": "browser"})
    session_id = start["session_id"]
    print(f"[session {session_id[:8]}  call {start['call_id']}]\n")
    print(f"MAYA:   {start['greeting']}\n")

    lines = sys.argv[1:]
    if lines:
        for line in lines:
            print(f"CALLER: {line}")
            reply = post("/chat", {"session_id": session_id, "message": line})
            flag = "  [verified]" if reply["verified"] else ""
            print(f"MAYA:   {reply['reply']}{flag}\n")
    else:
        while True:
            try:
                line = input("CALLER: ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not line or line in {"quit", "exit"}:
                break
            reply = post("/chat", {"session_id": session_id, "message": line})
            flag = "  [verified]" if reply["verified"] else ""
            print(f"MAYA:   {reply['reply']}{flag}\n")

    post(f"/calls/{session_id}/wrapup", {})
    print(f"[call wrapped up — summary agent running in background]")


if __name__ == "__main__":
    main()
