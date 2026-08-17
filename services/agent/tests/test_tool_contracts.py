"""Where the model's loose inputs meet the domain's strict API."""
import pytest
from langchain_core.messages import AIMessage

from app import summarizer
from app.domain_client import DomainError
from app.session import store

from .conftest import NOAH_PHONE
from .test_tools_and_graph import tool_result, verified


def test_natural_language_day_is_rejected_helpfully(fake_domain):
    out = tool_result(verified(fake_domain), "find_appointment_times", day="tomorrow")
    assert "YYYY-MM-DD" in out
    assert fake_domain.requests == []  # never sent to the domain as a 422


@pytest.mark.parametrize("spoken,expected", [("follow up", "Follow-up"), ("FOLLOW-UP", "Follow-up"), ("new patient", "New Patient"), ("newpatient", "New Patient")])
def test_visit_type_is_normalised(fake_domain, spoken, expected):
    out = tool_result(verified(fake_domain), "find_appointment_times", visit_type=spoken)
    assert expected in out and "slot_id=" in out


@pytest.mark.parametrize("name", ["Dr Chen", "Doctor Chen", "dr. marcus chen", "Chen"])
def test_provider_names_match_however_spoken(fake_domain, name):
    out = tool_result(verified(fake_domain), "find_appointment_times", provider_name=name)
    assert "Marcus Chen" in out and "Priya Shah" not in out


@pytest.mark.parametrize("bad", ["+", "555-0100", "01234567890123"])
def test_short_or_junk_phone_numbers_are_refused_before_the_domain(fake_domain, bad):
    s = store.create()
    assert "ten-digit" in tool_result(s, "start_verification", phone=bad)
    assert "ten-digit" in tool_result(s, "register_new_patient", first_name="A", last_name="B", date_of_birth="1990-01-01", phone=bad)
    assert fake_domain.requests == []


def test_dob_must_be_iso(fake_domain):
    out = tool_result(store.create(), "register_new_patient", first_name="A", last_name="B", date_of_birth="March 14 1991", phone=NOAH_PHONE)
    assert "YYYY-MM-DD" in out and fake_domain.requests == []


def test_reschedule_409_distinguishes_taken_from_pending(fake_domain):
    s = verified(fake_domain)
    tool_result(s, "book_appointment", slot_id=11)
    fake_domain.fail_with = DomainError(409, "Appointment is pending_change")
    out = tool_result(s, "reschedule_appointment", appointment_id=1, new_slot_id=12)
    assert "awaiting staff review" in out and "different time" not in out
    fake_domain.fail_with = DomainError(409, "That time was just taken — please pick another")
    assert "different time" in tool_result(s, "reschedule_appointment", appointment_id=1, new_slot_id=12)
    fake_domain.fail_with = DomainError(409, "Appointment is cancelled")
    assert "cancelled" in tool_result(s, "cancel_appointment", appointment_id=1)


def test_422_detail_lists_are_summarised(monkeypatch):
    """The real client against a fake domain that answers a pydantic 422."""
    import functools

    import httpx

    from app import domain_client

    def handler(request):
        return httpx.Response(
            422,
            json={"detail": [{"type": "date_from_datetime_parsing", "loc": ["query", "on"], "msg": "Input should be a valid date"}]},
        )

    monkeypatch.setattr(domain_client.httpx, "Client", functools.partial(httpx.Client, transport=httpx.MockTransport(handler)))
    with pytest.raises(DomainError) as exc:
        domain_client.search_slots(visit_type="Follow-up", on="tomorrow")
    assert exc.value.status == 422
    assert exc.value.message == "invalid input: on Input should be a valid date"


def test_cancelled_appointments_are_not_listed_as_upcoming(fake_domain):
    s = verified(fake_domain)
    tool_result(s, "book_appointment", slot_id=11)
    fake_domain.appointments[1]["status"] = "cancelled"
    assert "No upcoming appointments" in tool_result(s, "list_my_appointments")


def test_summariser_closes_call_even_without_transcript(fake_domain, monkeypatch):
    s = store.create()
    s.call_id = 55
    assert summarizer.summarise(s) is None
    assert [p for m, p, _ in fake_domain.requests if m == "PATCH"] == ["/calls/55"]


def test_summariser_skips_calls_that_never_opened(fake_domain):
    s = store.create()
    assert summarizer.summarise(s) is None
    assert fake_domain.requests == []


def test_summariser_writes_summary(fake_domain, scripted_llm, monkeypatch):
    from app.graph import run_turn

    s = store.create()
    s.call_id = 56
    scripted_llm.say("Sure, what day?")
    run_turn(s, "I'd like to book")

    class FakeSummaryLLM:
        def __init__(self, **kw):
            pass

        def invoke(self, prompt, config=None):
            return AIMessage(content='```json\n{"summary": "Caller wanted to book.", "intent": "booking", "sentiment": "positive"}\n```')

    monkeypatch.setattr(summarizer, "ChatOpenAI", FakeSummaryLLM)
    result = summarizer.summarise(s)
    assert result == {"summary": "Caller wanted to book.", "intent": "booking", "sentiment": "positive"}
    assert fake_domain.summaries == [result]


def test_summariser_survives_non_object_json(fake_domain, scripted_llm, monkeypatch):
    from app.graph import run_turn

    s = store.create()
    s.call_id = 57
    scripted_llm.say("ok")
    run_turn(s, "hi")

    class ListLLM:
        def __init__(self, **kw):
            pass

        def invoke(self, prompt, config=None):
            return AIMessage(content='["not", "an", "object"]')

    monkeypatch.setattr(summarizer, "ChatOpenAI", ListLLM)
    assert summarizer.summarise(s) is None


def test_list_providers_is_public_and_names_everyone(fake_domain):
    out = tool_result(store.create(), "list_providers")  # unverified caller, still allowed
    assert "Dr. Elena Vasquez — Dermatologist" in out and "Dr. Marcus Chen" in out and "Pediatric" in out
    assert "find_appointment_times" in out  # points the model at the next step


def test_switch_doctor_flow_end_to_end(fake_domain, scripted_llm):
    """List my visits → who are the doctors → Dr. Chen's times → move it."""
    from app.graph import run_turn

    s = verified(fake_domain)
    tool_result(s, "book_appointment", slot_id=12)  # Dr. Shah, three days out
    scripted_llm.call("list_my_appointments").call("list_providers").say("You're with Dr. Shah; we also have Dr. Vasquez and Dr. Chen. Who would you like?")
    turn = run_turn(s, "I want to switch to a different doctor — who do you have?")
    assert turn["tools_called"] == ["list_my_appointments", "list_providers"]
    assert "Dr. Chen" in turn["reply"]

    scripted_llm.call("find_appointment_times", provider_name="Dr. Chen").call("reschedule_appointment", appointment_id=1, new_slot_id=11).say("Done — Wednesday at 1 PM with Dr. Chen.")
    turn = run_turn(s, "Dr. Chen please, first thing you have")
    assert turn["tools_called"] == ["find_appointment_times", "reschedule_appointment"]
    assert fake_domain.appointments[1]["provider_name"] == "Dr. Marcus Chen"
