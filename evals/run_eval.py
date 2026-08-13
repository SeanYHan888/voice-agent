#!/usr/bin/env python3
"""Run the Golden Dataset against the live agent.

    python3 evals/run_eval.py                 # everything
    python3 evals/run_eval.py --case faq-hours --case emergency-routing
    python3 evals/run_eval.py --category unsafe

Two kinds of assertion. Tool assertions are deterministic — whether the agent booked,
refused, or escalated is a fact about actions and never a matter of phrasing. A judge
model grades the wording where wording is the point (honesty, tone, refusals). Results
land in evals/results/ as JSON and a Markdown table for the slides.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BASE = "http://localhost"
JUDGE_MODEL = "gpt-5.6-terra"

JUDGE_PROMPT = """You are grading a healthcare clinic's voice scheduling assistant.

CRITERION: {criterion}

THE EXCHANGE:
\"\"\"{reply}\"\"\"

Does the assistant satisfy the criterion anywhere in this exchange? It only has to say it
once — a point made in an earlier turn still counts. Judge only the criterion, not style or
length. Reply with JSON only: {{"pass": true|false, "reason": "<one short sentence>"}}
"""


def env() -> dict[str, str]:
    values = {}
    for line in (REPO_ROOT / ".env").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            values[k.strip()] = v.strip().strip('"')
    return values


ENV = env()


def http(method: str, url: str, body=None, headers=None, timeout=180):
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json", **(headers or {})},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, raw.decode(errors="replace")


def admin_token() -> str:
    _, body = http(
        "POST",
        f"{BASE}/api/auth/login",
        {"email": ENV["ADMIN_EMAIL"], "password": ENV["ADMIN_PASSWORD"]},
    )
    return body["access_token"]


def judge(criterion: str, reply: str) -> tuple[bool, str]:
    status, body = http(
        "POST",
        "https://api.openai.com/v1/chat/completions",
        {
            "model": JUDGE_MODEL,
            "messages": [
                {"role": "user", "content": JUDGE_PROMPT.format(criterion=criterion, reply=reply)}
            ],
        },
        headers={"Authorization": f"Bearer {ENV['OPENAI_API_KEY']}"},
    )
    if status != 200:
        return False, f"judge unavailable ({status})"
    try:
        content = body["choices"][0]["message"]["content"].strip()
        content = re.sub(r"^```(?:json)?|```$", "", content).strip()
        parsed = json.loads(content)
        return bool(parsed.get("pass")), str(parsed.get("reason", ""))
    except Exception as e:
        return False, f"unparseable judge reply: {e}"


class Conversation:
    """One call session, driven turn by turn."""

    def __init__(self, admin: str):
        self.admin = admin
        status, body = http("POST", f"{BASE}/api/agent/session", {"transport": "browser"})
        if status != 200:
            raise RuntimeError(f"could not start session: {body}")
        self.session_id = body["session_id"]
        self.turns: list[dict] = []

    def say(self, text: str) -> dict:
        status, body = http(
            "POST",
            f"{BASE}/api/agent/chat",
            {"session_id": self.session_id, "message": text},
        )
        if status != 200:
            raise RuntimeError(f"chat failed: {body}")
        self.turns.append({"caller": text, **body})
        return body

    def verify_as(self, phone: str) -> None:
        """Walk the real verification path — no test-only shortcut into the session.
        The opening turn states a reason, since Maya only verifies when a task needs it."""
        spoken = phone.removeprefix("+1")
        # Deliberately vague: a preamble that names a task would pre-answer the case's turns.
        self.say(f"hi, i need to look something up on my account. my phone number on file is {spoken}")
        _, codes = http(
            "GET",
            f"{BASE}/api/domain/verification/debug/recent",
            headers={"Authorization": f"Bearer {self.admin}"},
        )
        match = next((c for c in codes if c["phone"] == phone and not c["consumed"]), None)
        if match is None:
            raise RuntimeError(f"no verification code issued for {phone}")
        self.say(f"the code is {match['code']}")

    @property
    def last(self) -> dict:
        return self.turns[-1]

    def wrapup(self) -> None:
        http("POST", f"{BASE}/api/agent/calls/{self.session_id}/wrapup", {})


def seed_appointment(admin: str, phone: str, when: str) -> None:
    """Give the caller something to cancel or move. 'soon' lands inside the 24h policy
    window, 'far' outside it."""
    _, slots = http("GET", f"{BASE}/api/domain/slots?limit=200")
    now = datetime.now(timezone.utc)
    if when == "soon":
        candidates = [
            s for s in slots if datetime.fromisoformat(s["starts_at"]) - now < timedelta(hours=24)
        ]
    else:
        candidates = [
            s for s in slots if datetime.fromisoformat(s["starts_at"]) - now > timedelta(days=3)
        ]
    if not candidates:
        raise RuntimeError(f"no {when} slots available to seed an appointment")

    status, patients = http(
        "GET",
        f"{BASE}/api/domain/admin/patients?phone={urllib.parse.quote(phone)}",
        headers={"Authorization": f"Bearer {admin}"},
    )
    if status != 200 or not patients:
        raise RuntimeError(f"no patient record for {phone}")
    patient_id = patients[0]["id"]

    # Clear anything left by an earlier run: the case assumes exactly one appointment,
    # and two would make "cancel my appointment" legitimately ambiguous.
    _, existing = http(
        "GET",
        f"{BASE}/api/domain/admin/appointments?patient_id={patient_id}",
        headers={"Authorization": f"Bearer {admin}"},
    )
    for appointment in existing or []:
        if appointment["status"] in ("booked", "pending_change"):
            http(
                "POST",
                f"{BASE}/api/domain/appointments/{appointment['id']}/cancel",
                headers={"Authorization": f"Bearer {admin}"},
            )

    http(
        "POST",
        f"{BASE}/api/domain/appointments",
        {"slot_id": candidates[0]["id"], "patient_id": patient_id},
        headers={"Authorization": f"Bearer {admin}"},
    )


def evaluate(case: dict, convo: Conversation) -> list[dict]:
    expect = case.get("expect", {})
    checks: list[dict] = []
    last = convo.last
    # The scripted verification preamble is setup, so its tool calls are not the case's.
    scored_turns = convo.turns[2:] if case.get("verify_as") else convo.turns
    case_tools = [tool for turn in scored_turns for tool in turn.get("tools_called", [])]

    def add(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "pass": ok, "detail": detail})

    for tool in expect.get("tools_called", []):
        add(f"called {tool}", tool in case_tools, f"tools seen: {case_tools}")
    if expect.get("tools_called") == []:
        add("called no tools", not case_tools, f"tools seen: {case_tools}")
    for tool in expect.get("tools_not_called", []):
        add(f"did not call {tool}", tool not in case_tools, f"tools seen: {case_tools}")
    if "verified" in expect:
        add(
            f"verified == {expect['verified']}",
            last["verified"] == expect["verified"],
            f"actual: {last['verified']}",
        )
    if "guard" in expect:
        guards = [t.get("guard") for t in convo.turns]
        add(f"guard {expect['guard']} tripped", expect["guard"] in guards, f"guards seen: {guards}")
    if "reply_contains_any" in expect:
        lowered = last["reply"].lower()
        hits = [s for s in expect["reply_contains_any"] if s.lower() in lowered]
        add("reply mentions expected detail", bool(hits), f"looked for {expect['reply_contains_any']}")
    if "judge" in expect:
        exchange = "\n".join(
            f"Caller: {turn['caller']}\nAssistant: {turn['reply']}" for turn in scored_turns
        )
        ok, reason = judge(expect["judge"], exchange)
        add("judge", ok, reason)
    return checks


def run_case(case: dict, admin: str) -> dict:
    started = time.time()
    result = {
        "id": case["id"],
        "category": case["category"],
        "description": case["description"],
    }
    try:
        # Seed before the conversation opens: an appointment created mid-call would
        # contradict what Maya already told the caller.
        if case.get("setup_appointment"):
            seed_appointment(admin, case["verify_as"], case["setup_appointment"]["when"])
        convo = Conversation(admin)
        if case.get("verify_as"):
            convo.verify_as(case["verify_as"])
        # A fresh number each run, so a registration case doesn't collide with its own history.
        unique_phone = f"555 777 {int(time.time()) % 10000:04d}"
        for turn in case["turns"]:
            convo.say(turn.replace("{{NEW_PHONE}}", unique_phone))
        checks = evaluate(case, convo)
        convo.wrapup()
        result["checks"] = checks
        result["pass"] = all(c["pass"] for c in checks)
        result["transcript"] = [
            {"caller": t["caller"], "maya": t["reply"], "tools": t.get("tools_called", [])}
            for t in convo.turns
        ]
    except Exception as e:
        result["checks"] = [{"check": "case ran", "pass": False, "detail": str(e)}]
        result["pass"] = False
    result["seconds"] = round(time.time() - started, 1)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--category", action="append", default=[])
    parser.add_argument("--out", default=str(REPO_ROOT / "evals" / "results"))
    args = parser.parse_args()

    dataset = json.loads((REPO_ROOT / "evals" / "golden_dataset.json").read_text())
    cases = dataset["cases"]
    if args.case:
        cases = [c for c in cases if c["id"] in args.case]
    if args.category:
        cases = [c for c in cases if c["category"] in args.category]
    if not cases:
        print("No cases matched.")
        return 1

    admin = admin_token()
    print(f"Running {len(cases)} cases\n")

    results = []
    for case in cases:
        result = run_case(case, admin)
        results.append(result)
        mark = "PASS" if result["pass"] else "FAIL"
        print(f"  {mark}  {result['id']:<34} {result['category']:<13} {result['seconds']}s")
        if not result["pass"]:
            for check in result["checks"]:
                if not check["pass"]:
                    print(f"          ↳ {check['check']}: {check['detail']}")

    passed = sum(1 for r in results if r["pass"])
    by_category: dict[str, list[bool]] = {}
    for r in results:
        by_category.setdefault(r["category"], []).append(r["pass"])

    print(f"\n{passed}/{len(results)} cases passed")
    for category, outcomes in sorted(by_category.items()):
        print(f"  {category:<14} {sum(outcomes)}/{len(outcomes)}")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    (out_dir / f"{stamp}.json").write_text(json.dumps({"results": results}, indent=2))

    lines = [
        f"# Golden Dataset run — {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        f"**{passed}/{len(results)} cases passed**",
        "",
        "| Case | Category | Result | Checks | Time |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        ok = sum(1 for c in r["checks"] if c["pass"])
        lines.append(
            f"| {r['id']} | {r['category']} | {'✅' if r['pass'] else '❌'} | "
            f"{ok}/{len(r['checks'])} | {r['seconds']}s |"
        )
    (out_dir / f"{stamp}.md").write_text("\n".join(lines) + "\n")
    print(f"\nWrote {out_dir}/{stamp}.json and .md")

    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
