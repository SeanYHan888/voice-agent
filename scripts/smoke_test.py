#!/usr/bin/env python3
"""End-to-end check of the domain service's business rules and access control.

Runs against the Compose stack through the gateway. Stdlib only, so it needs no
virtualenv: `python3 scripts/smoke_test.py`. Exits non-zero on the first failure.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = "http://localhost"
REPO_ROOT = Path(__file__).resolve().parent.parent

passed = failed = 0


def env() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in (REPO_ROOT / ".env").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            values[k.strip()] = v.strip().strip('"')
    return values


ENV = env()


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def mint_agent_token(patient_id: int | None = None, call_id: int | None = None) -> str:
    """Stand in for agent-service, which signs call session tokens with the shared secret."""
    header = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    claims = {
        "sub": "agent",
        "role": "agent",
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }
    if patient_id is not None:
        claims["patient_id"] = patient_id
    if call_id is not None:
        claims["call_id"] = call_id
    payload = b64(json.dumps(claims).encode())
    signing_input = f"{header}.{payload}".encode()
    signature = hmac.new(ENV["JWT_SECRET"].encode(), signing_input, hashlib.sha256).digest()
    return f"{header}.{payload}.{b64(signature)}"


def call(method: str, path: str, body=None, token: str | None = None) -> tuple[int, object]:
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"}
        | ({"Authorization": f"Bearer {token}"} if token else {}),
        method=method,
    )
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, raw.decode(errors="replace")


def check(label: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}{f' — {detail}' if detail else ''}")


def section(name: str) -> None:
    print(f"\n{name}")


def main() -> int:
    unique = int(time.time())

    section("Health")
    for svc in ("auth", "domain", "agent"):
        status, body = call("GET", f"/api/{svc}/healthz")
        check(f"{svc} healthy", status == 200 and body.get("ok"), str(body))

    section("Accounts")
    status, body = call(
        "POST",
        "/api/auth/register",
        {"email": f"ava{unique}@example.com", "password": "testpass123"},
    )
    check("patient registers", status == 201, str(body))
    ava_token = body["access_token"]

    status, body = call(
        "POST",
        "/api/auth/register",
        {"email": f"liam{unique}@example.com", "password": "testpass123"},
    )
    liam_token = body["access_token"]

    status, body = call(
        "POST",
        "/api/auth/login",
        {"email": ENV["ADMIN_EMAIL"], "password": ENV["ADMIN_PASSWORD"]},
    )
    check("admin logs in", status == 200 and body.get("role") == "admin", str(body))
    admin_token = body["access_token"]

    section("Claiming a clinic record")
    # Records stay claimed between runs, so take whichever two are still free.
    _, all_patients = call("GET", "/api/domain/admin/patients", token=admin_token)
    unclaimed = [p for p in all_patients if p["user_id"] is None]
    if len(unclaimed) < 2:
        print("  SKIP  no unclaimed patient records left — run `docker compose down -v` to reseed")
        return 1
    first, second = unclaimed[0], unclaimed[1]

    status, _ = call("GET", "/api/domain/patients/me", token=ava_token)
    check("unlinked account has no patient record", status == 404)

    status, _ = call(
        "POST",
        "/api/domain/patients/claim",
        {"phone": first["phone"], "dob": "1900-01-01"},
        token=ava_token,
    )
    check("claim with wrong date of birth is refused", status == 404)

    status, body = call(
        "POST",
        "/api/domain/patients/claim",
        {"phone": first["phone"], "dob": first["dob"]},
        token=ava_token,
    )
    check("claim with matching details links the record", status == 200, str(body))
    ava_patient_id = body["id"]

    status, _ = call(
        "POST",
        "/api/domain/patients/claim",
        {"phone": first["phone"], "dob": first["dob"]},
        token=liam_token,
    )
    check("a claimed record cannot be taken over", status == 409)

    status, body = call(
        "POST",
        "/api/domain/patients/claim",
        {"phone": second["phone"], "dob": second["dob"]},
        token=liam_token,
    )
    liam_patient_id = body["id"]

    section("Availability and booking")
    status, slots = call("GET", "/api/domain/slots?limit=200")
    check("slot search needs no login", status == 200 and len(slots) > 0)

    now = datetime.now(timezone.utc)
    soon = [s for s in slots if datetime.fromisoformat(s["starts_at"]) - now < timedelta(hours=24)]
    later = [s for s in slots if datetime.fromisoformat(s["starts_at"]) - now > timedelta(days=2)]
    check("fixture has slots inside and beyond the 24h window", bool(soon) and bool(later))

    status, appt = call(
        "POST", "/api/domain/appointments", {"slot_id": later[0]["id"]}, token=ava_token
    )
    check("patient books a future slot", status == 201, str(appt))
    far_appointment_id = appt["id"]

    status, _ = call(
        "POST", "/api/domain/appointments", {"slot_id": later[0]["id"]}, token=liam_token
    )
    check("double-booking the same slot is refused", status == 409)

    status, mine = call("GET", "/api/domain/appointments/me", token=ava_token)
    check(
        "appointment appears in my list",
        status == 200 and any(a["id"] == far_appointment_id for a in mine),
        f"listed: {[a['id'] for a in mine]}",
    )

    section("Access control")
    status, _ = call(
        "POST", f"/api/domain/appointments/{far_appointment_id}/cancel", token=liam_token
    )
    check("one patient cannot cancel another's appointment", status == 403)

    status, _ = call("GET", "/api/domain/admin/tasks", token=ava_token)
    check("patient cannot read the admin queue", status == 403)

    status, _ = call("GET", "/api/domain/admin/stats", token=ava_token)
    check("patient cannot read admin stats", status == 403)

    status, _ = call("GET", "/api/domain/appointments/me")
    check("no token is rejected", status == 401)

    status, _ = call("GET", "/api/domain/appointments/me", token="not-a-real-token")
    check("forged token is rejected", status == 401)

    section("Voice session identity")
    anon = mint_agent_token()
    status, body = call(
        "POST", "/api/domain/appointments", {"slot_id": later[1]["id"]}, token=anon
    )
    check("unverified voice session cannot book", status == 403, str(body))

    status, _ = call("GET", "/api/domain/slots", token=anon)
    check("unverified voice session can still browse availability", status == 200)

    section("Verification")
    status, body = call(
        "POST", "/api/domain/verification/request", {"phone": "+15550100103"}, token=anon
    )
    check("code issued for a known number", status == 200 and body["sent"], str(body))
    check("phone number is masked in the response", "0103" in body["masked_phone"])

    status, body = call(
        "POST", "/api/domain/verification/request", {"phone": "+19995550000"}, token=anon
    )
    check("unknown number reports no match rather than erroring", status == 200 and not body["sent"])

    status, codes = call("GET", "/api/domain/verification/debug/recent", token=admin_token)
    check("admin can read pending codes for the demo", status == 200 and len(codes) > 0)
    noah_code = next(c["code"] for c in codes if c["phone"] == "+15550100103")

    status, _ = call("GET", "/api/domain/verification/debug/recent", token=ava_token)
    check("patient cannot read pending codes", status == 403)

    status, body = call(
        "POST",
        "/api/domain/verification/confirm",
        {"phone": "+15550100103", "code": "000000"},
        token=anon,
    )
    check("wrong code is refused", status == 200 and not body["verified"])

    status, body = call(
        "POST",
        "/api/domain/verification/confirm",
        {"phone": "+15550100103", "code": noah_code},
        token=anon,
    )
    check("correct code verifies the caller", status == 200 and body["verified"], str(body))
    noah_patient_id = body["patient_id"]

    status, body = call(
        "POST",
        "/api/domain/verification/confirm",
        {"phone": "+15550100103", "code": noah_code},
        token=anon,
    )
    check("a code cannot be reused", status == 200 and not body["verified"])

    section("Verified voice session books")
    status, call_body = call(
        "POST", "/api/domain/calls", {"transport": "browser"}, token=anon
    )
    check("agent opens a call record", status == 201, str(call_body))
    call_id = call_body["id"]

    verified = mint_agent_token(patient_id=noah_patient_id, call_id=call_id)
    status, appt = call(
        "POST", "/api/domain/appointments", {"slot_id": later[1]["id"]}, token=verified
    )
    check("verified voice session books successfully", status == 201, str(appt))
    check("booking is attributed to the call", appt is not None)

    section("24-hour approval policy")
    status, near_appt = call(
        "POST", "/api/domain/appointments", {"slot_id": soon[0]["id"]}, token=verified
    )
    check("books a slot inside the 24h window", status == 201, str(near_appt))

    status, body = call(
        "POST", f"/api/domain/appointments/{near_appt['id']}/cancel", token=verified
    )
    check("cancelling inside 24h needs approval", status == 200 and body["requires_approval"], str(body))
    check("appointment is held pending review", body["status"] == "pending_change")

    status, body = call(
        "POST", f"/api/domain/appointments/{far_appointment_id}/cancel", token=ava_token
    )
    check("cancelling outside 24h happens immediately", status == 200 and not body["requires_approval"])
    check("appointment is cancelled", body["status"] == "cancelled")

    status, tasks = call("GET", "/api/domain/admin/tasks?kind=approval", token=admin_token)
    check("approval task is queued for staff", status == 200 and len(tasks) >= 1, str(tasks))
    task_id = tasks[0]["id"]

    status, body = call("POST", f"/api/domain/admin/tasks/{task_id}/approve", token=admin_token)
    check("admin approves the held cancellation", status == 200, str(body))

    status, tasks_after = call("GET", "/api/domain/admin/tasks?status=approved", token=admin_token)
    check("task moves out of the open queue", any(t["id"] == task_id for t in tasks_after))

    status, _ = call("POST", f"/api/domain/admin/tasks/{task_id}/approve", token=admin_token)
    check("a resolved task cannot be approved twice", status == 409)

    section("Escalation, summary, feedback")
    status, body = call(
        "POST",
        "/api/domain/escalations",
        {"call_id": call_id, "reason": "medical_question", "detail": "Caller asked about a mole"},
        token=verified,
    )
    check("agent escalates to a human", status == 201, str(body))

    status, _ = call(
        "PATCH",
        f"/api/domain/calls/{call_id}",
        {"transcript": "Caller booked a follow-up."},
        token=verified,
    )
    check("agent closes the call", status == 200)

    status, _ = call(
        "POST",
        f"/api/domain/calls/{call_id}/summary",
        {"summary": "Booked a follow-up visit.", "intent": "booking", "sentiment": "positive"},
        token=verified,
    )
    check("post-call summary is stored", status == 201)

    noah_portal = mint_agent_token(patient_id=noah_patient_id)
    status, calls_list = call("GET", "/api/domain/calls/me", token=noah_portal)
    check("patient sees their call history", status == 200 and len(calls_list) >= 1)
    check("history carries the summary", calls_list[0]["summary"] is not None)

    status, _ = call(
        "POST",
        "/api/domain/feedback",
        {"call_id": call_id, "stars": 5, "comment": "Very quick."},
        token=noah_portal,
    )
    check("patient leaves feedback", status == 201)

    status, _ = call(
        "POST", "/api/domain/feedback", {"call_id": call_id, "stars": 1}, token=noah_portal
    )
    check("feedback cannot be left twice", status == 409)

    status, _ = call(
        "POST", "/api/domain/feedback", {"call_id": call_id, "stars": 3}, token=ava_token
    )
    check("feedback on someone else's call is refused", status == 403)

    section("Admin analytics")
    status, stats = call("GET", "/api/domain/admin/stats", token=admin_token)
    check("stats endpoint responds", status == 200, str(stats))
    check("stats count calls", stats["total_calls"] >= 1)
    check("stats average feedback", stats["avg_feedback"] > 0)
    check("stats report booking conversion", "booking_conversion" in stats)

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
