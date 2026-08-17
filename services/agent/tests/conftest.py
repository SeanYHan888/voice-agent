"""Test harness for the agent service.

Everything outside this service is faked so the pipeline runs offline and deterministically:

- FakeDomain stands in for the domain service (patients, codes, slots, appointments) with
  the same request/response shapes as services/domain, wired in under domain_client._request.
- ScriptedLLM stands in for the OpenAI model: each test scripts the AIMessages the model
  "returns", tool calls included, so the graph's real ToolNode, guards, checkpointing and
  session plumbing are exercised without a network.
- Checkpoints use LangGraph's MemorySaver instead of Postgres.
"""
import os
from datetime import datetime, timedelta, timezone

os.environ["OPENAI_API_KEY"] = "test-key"
os.environ["ELEVENLABS_LLM_API_KEY"] = "el-test-key"
os.environ["DATABASE_URL"] = "postgresql+psycopg://nobody@127.0.0.1:1/none"
os.environ["LANGFUSE_PUBLIC_KEY"] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from langchain_core.messages import AIMessage  # noqa: E402
from langgraph.checkpoint.memory import MemorySaver  # noqa: E402

from app import domain_client, graph, main  # noqa: E402
from app.domain_client import DomainError  # noqa: E402
from app.session import store  # noqa: E402

NOW = datetime(2026, 8, 17, 8, 0, tzinfo=timezone.utc)
EMMA_PHONE = "+15550100101"
NOAH_PHONE = "+15550100104"


class FakeDomain:
    """In-memory stand-in for the domain service. Only what the agent actually calls."""

    def __init__(self):
        self.patients = {
            1: {"id": 1, "first_name": "Emma", "last_name": "Rossi", "phone": EMMA_PHONE},
            4: {"id": 4, "first_name": "Noah", "last_name": "Kim", "phone": NOAH_PHONE},
        }
        self.codes: list[dict] = []  # newest last
        self.slots = {
            10: self._slot(10, "Dr. Priya Shah", "Follow-up", NOW + timedelta(hours=3)),
            11: self._slot(11, "Dr. Marcus Chen", "Follow-up", NOW + timedelta(days=2, hours=5)),
            12: self._slot(12, "Dr. Priya Shah", "New Patient", NOW + timedelta(days=3)),
        }
        self.appointments: dict[int, dict] = {}
        self.calls: list[dict] = []
        self.escalations: list[dict] = []
        self.summaries: list[dict] = []
        self.requests: list[tuple[str, str, dict]] = []  # (method, path, claims)
        self.next_call_id = 100
        self.next_appt_id = 1
        self.fail_with: DomainError | Exception | None = None

    @staticmethod
    def _slot(id, provider, visit_type, starts_at):
        return {
            "id": id,
            "provider_name": provider,
            "visit_type": visit_type,
            "starts_at": starts_at.isoformat(),
            "status": "open",
        }

    # -- dispatcher -------------------------------------------------------------
    def request(self, method, path, session=None, **kwargs):
        import jwt

        claims = (
            jwt.decode(session.token(), options={"verify_signature": False}) if session else {}
        )
        self.requests.append((method, path, claims))
        if self.fail_with is not None:
            raise self.fail_with
        body = kwargs.get("json") or {}
        params = kwargs.get("params") or {}
        patient_id = claims.get("patient_id")

        if method == "GET" and path == "/providers":
            return [
                {"id": 1, "name": "Dr. Elena Vasquez", "title": "Dermatologist"},
                {"id": 2, "name": "Dr. Marcus Chen", "title": "Dermatologist"},
                {"id": 3, "name": "Dr. Priya Shah", "title": "Pediatric Dermatologist"},
            ]
        if method == "GET" and path == "/slots":
            return [
                s
                for s in self.slots.values()
                if s["status"] == "open" and s["visit_type"] == params.get("visit_type")
            ]
        if path == "/faq/search":
            return {"results": [{"title": "Clinic hours", "text": "Open 9 to 5 weekdays."}]}
        if path == "/verification/request":
            patient = self._by_phone(body["phone"])
            if patient is None:
                return {"sent": False, "message": "No patient record matches that number"}
            self.codes.append({"patient_id": patient["id"], "code": "123456", "used": False})
            return {"sent": True, "masked_phone": "•••••" + body["phone"][-4:], "message": "sent"}
        if path == "/verification/confirm":
            patient = self._by_phone(body["phone"])
            if patient is None:
                raise DomainError(404, "No patient record matches that number")
            pending = [c for c in self.codes if c["patient_id"] == patient["id"] and not c["used"]]
            if not pending:
                return {"verified": False, "message": "No pending code — request a new one"}
            if pending[-1]["code"] != body["code"].strip():
                return {"verified": False, "message": "That code doesn't match"}
            pending[-1]["used"] = True
            return {"verified": True, "patient_id": patient["id"], "first_name": patient["first_name"], "message": "Verified"}
        if path == "/patients/register":
            if self._by_phone(body["phone"]) is not None:
                raise DomainError(409, "A patient with that phone number already exists")
            new_id = max(self.patients) + 1
            self.patients[new_id] = {"id": new_id, **body}
            return {"id": new_id, **body}
        if path == "/patients/me":
            return self.patients[patient_id]
        if path == "/appointments" and method == "POST":
            if patient_id is None:
                raise DomainError(403, "Verification required")
            slot = self.slots[body["slot_id"]]
            if slot["status"] != "open":
                raise DomainError(409, "That time was just taken — please pick another")
            slot["status"] = "booked"
            appt = {
                "id": self.next_appt_id,
                "patient_id": patient_id,
                "slot_id": slot["id"],
                "starts_at": slot["starts_at"],
                "provider_name": slot["provider_name"],
                "visit_type": slot["visit_type"],
                "status": "booked",
                "requires_approval": False,
                "message": "Booked",
            }
            self.next_appt_id += 1
            self.appointments[appt["id"]] = appt
            return appt
        if path == "/appointments/me":
            return [a for a in self.appointments.values() if a["patient_id"] == patient_id]
        if path.startswith("/appointments/") and path.endswith("/cancel"):
            appt = self._own_appt(path, patient_id)
            within = datetime.fromisoformat(appt["starts_at"]) - NOW < timedelta(hours=24)
            if within:
                appt["status"] = "pending_change"
                return {**appt, "requires_approval": True, "message": "staff will review"}
            appt["status"] = "cancelled"
            return {**appt, "requires_approval": False, "message": "Appointment cancelled"}
        if path.startswith("/appointments/") and path.endswith("/reschedule"):
            appt = self._own_appt(path, patient_id)
            new_slot = self.slots[body["new_slot_id"]]
            if new_slot["status"] != "open":
                raise DomainError(409, "That time was just taken — please pick another")
            within = datetime.fromisoformat(appt["starts_at"]) - NOW < timedelta(hours=24)
            if within:
                appt["status"] = "pending_change"
                return {**appt, "requires_approval": True, "message": "staff will review"}
            appt.update(slot_id=new_slot["id"], starts_at=new_slot["starts_at"], provider_name=new_slot["provider_name"])
            return {**appt, "requires_approval": False, "message": "Appointment rescheduled"}
        if path == "/calls" and method == "POST":
            call = {"id": self.next_call_id, **body}
            self.next_call_id += 1
            self.calls.append(call)
            return call
        if path.startswith("/calls/") and path.endswith("/summary"):
            self.summaries.append(body)
            return {"ok": True}
        if path.startswith("/calls/") and method == "PATCH":
            return {"ok": True}
        if path == "/escalations":
            self.escalations.append({**body, "patient_id": patient_id})
            return {"id": len(self.escalations), **body}
        raise AssertionError(f"FakeDomain has no route for {method} {path}")

    def _by_phone(self, phone):
        return next((p for p in self.patients.values() if p["phone"] == phone), None)

    def _own_appt(self, path, patient_id):
        appt_id = int(path.split("/")[2])
        appt = self.appointments.get(appt_id)
        if appt is None:
            raise DomainError(404, "Unknown appointment")
        if appt["patient_id"] != patient_id:
            raise DomainError(403, "Not your appointment")
        return appt


class ScriptedLLM:
    """Returns pre-scripted AIMessages in order; records what it was asked."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls: list[list] = []

    def invoke(self, messages, config=None):
        self.calls.append(list(messages))
        if not self.responses:
            return AIMessage(content="(scripted model has nothing more to say)")
        step = self.responses.pop(0)
        if isinstance(step, Exception):
            raise step
        return step

    def say(self, text):
        self.responses.append(AIMessage(content=text))
        return self

    def call(self, name, **args):
        self.responses.append(
            AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call_{len(self.responses)}"}])
        )
        return self


@pytest.fixture
def fake_domain(monkeypatch):
    fake = FakeDomain()
    monkeypatch.setattr(domain_client, "_request", fake.request)
    return fake


@pytest.fixture
def scripted_llm(monkeypatch):
    llm = ScriptedLLM()
    monkeypatch.setattr(graph, "_llm", llm)
    monkeypatch.setattr(graph, "_get_llm", lambda: llm)
    return llm


@pytest.fixture(autouse=True)
def fresh_graph(monkeypatch):
    """Memory checkpointer, fresh compiled graph and empty session store per test."""
    monkeypatch.setattr(graph, "_make_checkpointer", lambda: MemorySaver())
    monkeypatch.setattr(graph, "_compiled", None)
    monkeypatch.setattr(graph, "_langfuse_handler", None)
    store._sessions.clear()
    yield
    store._sessions.clear()


@pytest.fixture
def client(fake_domain, scripted_llm):
    return TestClient(main.app)


def voice_payload(user_text, session_id=None, conversation_id=None, prior=(), stream=False):
    """The shape ElevenLabs posts to /v1/chat/completions once the agent's system prompt is
    configured per docs/elevenlabs-setup.md."""
    system_lines = []
    system_lines.append(f"session_id={session_id}" if session_id else "session_id={{session_id}}")
    system_lines.append(f"conversation_id={conversation_id or 'conv_' + 'x' * 12}")
    messages = [{"role": "system", "content": "\n".join(system_lines)}]
    for role, text in prior:
        messages.append({"role": role, "content": text})
    messages.append({"role": "user", "content": user_text})
    return {"model": "gpt-5.6-luna", "messages": messages, "stream": stream}


EL_HEADERS = {"Authorization": "Bearer el-test-key"}
