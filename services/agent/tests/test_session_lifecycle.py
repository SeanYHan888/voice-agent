"""Session identity over time: restarts, idle expiry, concurrent turns, odd platform payloads."""
import threading
import time

from app import graph, main
from app.main import _extract_session_id, _last_user_message
from app.session import CALL_IDLE_SECONDS, SESSION_TTL_SECONDS, store

from .conftest import EL_HEADERS, NOAH_PHONE, voice_payload


def test_marker_never_captures_the_next_keyword():
    """Whitespace-collapsed prompt: 'session_id= conversation_id=conv_x' must not make every
    call share a session literally named 'conversation_id'."""
    payload = {"messages": [{"role": "system", "content": "session_id= conversation_id=conv_abcdefghijkl"}]}
    assert _extract_session_id(payload, "") == "conv_abcdefghijkl"
    payload = {"messages": [{"role": "system", "content": "session_id=\tconversation_id: conv_abcdefghijkl"}]}
    assert _extract_session_id(payload, "") == "conv_abcdefghijkl"


def test_trailing_assistant_message_does_not_replay_previous_user_turn():
    payload = {"messages": [{"role": "user", "content": "555-010-0104"}, {"role": "assistant", "content": "Code sent."}]}
    assert _last_user_message(payload) == ""


def test_verified_identity_survives_agent_restart(client, fake_domain, scripted_llm):
    scripted_llm.call("start_verification", phone=NOAH_PHONE).say("Code sent")
    client.post("/v1/chat/completions", headers=EL_HEADERS, json=voice_payload("verify", session_id="restart-session-01"))
    scripted_llm.call("finish_verification", code="123456").say("Verified")
    client.post("/v1/chat/completions", headers=EL_HEADERS, json=voice_payload("123456", session_id="restart-session-01"))
    call_id = store.get("restart-session-01").call_id
    assert store.get("restart-session-01").patient_id == 4

    # The process restarts: in-memory sessions are gone, checkpoints (MemorySaver here,
    # Postgres in production) survive.
    store._sessions.clear()

    scripted_llm.call("list_my_appointments").say("Nothing booked yet.")
    r = client.post("/v1/chat/completions", headers=EL_HEADERS, json=voice_payload("what do I have?", session_id="restart-session-01"))
    assert r.json()["choices"][0]["message"]["content"] == "Nothing booked yet."
    session = store.get("restart-session-01")
    assert session.patient_id == 4 and session.patient_first_name == "Noah"
    assert session.call_id == call_id  # same call record, not a second one
    assert fake_domain.requests[-1][1] == "/appointments/me" and fake_domain.requests[-1][2]["patient_id"] == 4


def test_wrapup_after_restart_finds_the_call(client, fake_domain, scripted_llm, monkeypatch):
    scripted_llm.say("Hello!")
    client.post("/chat", json={"session_id": "restart-chat-0001", "message": "hi"})
    call_id = store.get("restart-chat-0001").call_id
    store._sessions.clear()
    summarised = []
    monkeypatch.setattr(main, "summarise", lambda s: summarised.append(s.call_id))
    r = client.post("/calls/restart-chat-0001/wrapup")
    assert r.status_code == 200 and r.json()["call_id"] == call_id
    assert summarised == [call_id]


def test_idle_sessions_are_pruned_and_summarised(client, fake_domain, scripted_llm, monkeypatch):
    scripted_llm.say("Hi.").say("Hi again.")
    client.post("/chat", json={"session_id": "idle-session-000001", "message": "hello"})
    idle = store.get("idle-session-000001")
    idle.last_seen -= CALL_IDLE_SECONDS + 1
    summarised = []
    monkeypatch.setattr(main, "summarise", lambda s: summarised.append(s.id))
    client.post("/chat", json={"session_id": "busy-session-000001", "message": "hello"})
    assert store.get("idle-session-000001") is None
    assert store.get("busy-session-000001") is not None
    assert summarised == ["idle-session-000001"]


def test_activity_refreshes_expiry(client, fake_domain, scripted_llm):
    scripted_llm.say("Hi.").say("Still here.")
    client.post("/chat", json={"session_id": "long-call-0000001", "message": "hello"})
    s = store.get("long-call-0000001")
    s.created_at -= SESSION_TTL_SECONDS * 3  # created long ago…
    client.post("/chat", json={"session_id": "long-call-0000001", "message": "still talking"})
    assert store.get("long-call-0000001") is s  # …but active, so kept


def test_concurrent_turns_on_one_session_are_serialised(client, fake_domain, scripted_llm, monkeypatch):
    """Barge-in: two voice turns for the same session at once must not fork the checkpoint."""
    inside, overlap = [], []
    real_invoke = scripted_llm.invoke

    def slow_invoke(messages, config=None):
        inside.append(1)
        if len(inside) > 1:
            overlap.append(1)
        time.sleep(0.05)
        inside.pop()
        return real_invoke(messages, config)

    monkeypatch.setattr(scripted_llm, "invoke", slow_invoke)
    scripted_llm.say("one").say("two")

    statuses = []

    def turn(text):
        r = client.post("/v1/chat/completions", headers=EL_HEADERS, json=voice_payload(text, session_id="barge-session-0001"))
        statuses.append((text, r.status_code, r.text[:200]))

    threads = [threading.Thread(target=turn, args=(t,)) for t in ("first", "second")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert overlap == []
    assert [st for _, st, _ in statuses] == [200, 200], statuses
    history = [m.content for m in graph.transcript_of(store.get("barge-session-0001")) if m.type == "human"]
    assert sorted(history) == ["first", "second"]
    assert len(fake_domain.calls) == 1  # one call record, not one per racing turn


def test_session_start_does_not_open_a_call_until_someone_speaks(client, fake_domain, scripted_llm):
    """Loading the page is not a call. Six 'in progress' rows came from six page loads."""
    r = client.post("/session", json={"transport": "browser"})
    assert r.status_code == 200 and r.json()["call_id"] is None
    assert fake_domain.calls == []
    scripted_llm.say("Hi!")
    client.post("/chat", json={"session_id": r.json()["session_id"], "message": "hello"})
    assert len(fake_domain.calls) == 1
    assert store.get(r.json()["session_id"]).call_id == fake_domain.calls[0]["id"]


def test_wrapup_of_a_session_that_never_spoke_is_a_quiet_no_op(client, fake_domain, monkeypatch):
    r = client.post("/session", json={"transport": "browser"})
    calls = []
    monkeypatch.setattr(main, "summarise", lambda s: calls.append(s.call_id))
    assert client.post(f"/calls/{r.json()['session_id']}/wrapup").status_code == 200
    assert calls == [None]  # summarise() itself returns early on call_id None


def test_background_sweep_closes_idle_calls_without_waiting_for_traffic(client, fake_domain, scripted_llm, monkeypatch):
    scripted_llm.say("Hi.")
    client.post("/chat", json={"session_id": "hung-up-session-01", "message": "hello"})
    store.get("hung-up-session-01").last_seen -= CALL_IDLE_SECONDS + 1
    summarised = []
    monkeypatch.setattr(main, "summarise", lambda s: summarised.append(s.id))
    main.sweep_idle_sessions()  # what the timer thread calls every minute
    assert summarised == ["hung-up-session-01"] and store.get("hung-up-session-01") is None


def test_call_idle_ttl_is_shorter_than_token_life():
    assert CALL_IDLE_SECONDS < SESSION_TTL_SECONDS
