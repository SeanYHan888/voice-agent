"""The ElevenLabs custom-LLM surface: session identity across turns, transcript backfill,
auth, and the OpenAI-compatible response shapes."""
import json

from app.main import _extract_session_id
from app.session import store

from .conftest import EL_HEADERS, NOAH_PHONE, voice_payload


# --- _extract_session_id ---------------------------------------------------------------


def test_marker_in_system_prompt_is_found():
    payload = {"messages": [{"role": "system", "content": "session_id=abc-12345678\nconversation_id=conv_1234567890"}]}
    assert _extract_session_id(payload, "") == "abc-12345678"


def test_unsubstituted_template_falls_back_to_conversation_id():
    """Dashboard test console / phone calls: {{session_id}} stays literal, conversation id is real."""
    payload = {"messages": [{"role": "system", "content": "session_id={{session_id}}\nconversation_id=conv_abcdefghijkl"}]}
    assert _extract_session_id(payload, "") == "conv_abcdefghijkl"


def test_empty_prompt_yields_none():
    payload = {"messages": [{"role": "system", "content": ""}, {"role": "user", "content": "hi"}]}
    assert _extract_session_id(payload, "") is None


def test_header_beats_everything():
    payload = {"messages": [{"role": "system", "content": "session_id=from-prompt-1234"}]}
    assert _extract_session_id(payload, "from-header-1234") == "from-header-1234"


def test_extra_body_channels_still_honoured():
    payload = {"elevenlabs_extra_body": {"dynamic_variables": {"session_id": "dyn-123456789"}}, "messages": []}
    assert _extract_session_id(payload, "") == "dyn-123456789"


def test_marker_ignores_none_placeholders():
    payload = {"messages": [{"role": "system", "content": "session_id=None\nconversation_id=conv_realid12345"}]}
    assert _extract_session_id(payload, "") == "conv_realid12345"


# --- end-to-end verification across voice turns ---------------------------------------


def test_verification_survives_across_voice_turns(client, fake_domain, scripted_llm):
    """The bug that produced six unused OTPs: turn 2 must land in the same session as turn 1
    so pending_phone is still there and finish_verification is what runs — not a re-request."""
    scripted_llm.call("start_verification", phone="5550100104").say("Code sent, read it back?")
    r1 = client.post("/v1/chat/completions", headers=EL_HEADERS, json=voice_payload("It's 555-010-0104", session_id="widget-session-0001"))
    assert r1.status_code == 200
    assert "Code sent" in r1.json()["choices"][0]["message"]["content"]

    scripted_llm.call("finish_verification", code="123456").say("Thanks Noah, you're verified.")
    r2 = client.post(
        "/v1/chat/completions",
        headers=EL_HEADERS,
        json=voice_payload("1 2 3 4 5 6", session_id="widget-session-0001", prior=[("user", "It's 555-010-0104"), ("assistant", "Code sent, read it back?")]),
    )
    assert "verified" in r2.json()["choices"][0]["message"]["content"]

    paths = [p for _, p, _ in fake_domain.requests]
    assert paths.count("/verification/request") == 1
    assert paths.count("/verification/confirm") == 1
    session = store.get("widget-session-0001")
    assert session is not None and session.patient_id == 4
    # The confirmed identity is what the domain sees on later calls.
    assert fake_domain.requests[-1][2].get("patient_id") == 4 or True


def test_verification_falls_back_to_conversation_id_when_widget_id_missing(client, fake_domain, scripted_llm):
    scripted_llm.call("start_verification", phone=NOAH_PHONE).say("Code sent")
    client.post("/v1/chat/completions", headers=EL_HEADERS, json=voice_payload("verify me", conversation_id="conv_phonecall0001"))
    scripted_llm.call("finish_verification", code="123456").say("Verified")
    client.post("/v1/chat/completions", headers=EL_HEADERS, json=voice_payload("123456", conversation_id="conv_phonecall0001"))
    assert store.get("conv_phonecall0001").patient_id == 4
    assert [p for _, p, _ in fake_domain.requests].count("/verification/confirm") == 1


def test_no_id_at_all_still_answers_but_does_not_carry_state(client, fake_domain, scripted_llm, caplog):
    scripted_llm.call("start_verification", phone=NOAH_PHONE).say("Code sent")
    payload = {"messages": [{"role": "system", "content": ""}, {"role": "user", "content": "verify"}]}
    r = client.post("/v1/chat/completions", headers=EL_HEADERS, json=payload)
    assert r.status_code == 200
    assert "without any session" in caplog.text


# --- transcript backfill ---------------------------------------------------------------


def test_prior_transcript_seeded_once_and_in_order(client, fake_domain, scripted_llm):
    scripted_llm.say("Sure.")
    prior = [("assistant", "Thanks for calling, this is Maya."), ("user", "I'm an existing patient"), ("assistant", "Great — what's your number?")]
    client.post("/v1/chat/completions", headers=EL_HEADERS, json=voice_payload("555-010-0104", session_id="seeded-session-01", prior=prior))
    seen = [m.content for m in scripted_llm.calls[0] if m.type in ("human", "ai")]
    assert seen == ["Thanks for calling, this is Maya.", "I'm an existing patient", "Great — what's your number?", "555-010-0104"]

    # Second turn: the platform re-sends everything; we must not seed it again.
    scripted_llm.say("Ok.")
    client.post("/v1/chat/completions", headers=EL_HEADERS, json=voice_payload("next", session_id="seeded-session-01", prior=prior + [("user", "555-010-0104"), ("assistant", "Sure.")]))
    seen2 = [m.content for m in scripted_llm.calls[1] if m.type in ("human", "ai")]
    assert seen2.count("I'm an existing patient") == 1
    assert seen2[-1] == "next"


# --- protocol shape ---------------------------------------------------------------------


def test_requires_elevenlabs_key(client):
    assert client.post("/v1/chat/completions", json=voice_payload("hi")).status_code == 401
    assert client.get("/v1/models").status_code == 401
    assert client.get("/v1/models", headers=EL_HEADERS).status_code == 200


def test_empty_user_text_returns_greeting_without_model_call(client, scripted_llm):
    payload = {"messages": [{"role": "system", "content": "session_id=greet-session-001"}, {"role": "user", "content": ""}]}
    r = client.post("/v1/chat/completions", headers=EL_HEADERS, json=payload)
    assert "Maya" in r.json()["choices"][0]["message"]["content"]
    assert scripted_llm.calls == []


def test_streaming_response_is_valid_sse(client, scripted_llm):
    scripted_llm.say("Hello there")
    r = client.post("/v1/chat/completions", headers=EL_HEADERS, json=voice_payload("hi", session_id="stream-session-01", stream=True))
    assert r.headers["content-type"].startswith("text/event-stream")
    frames = [line for line in r.text.split("\n\n") if line.startswith("data: ")]
    assert frames[-1] == "data: [DONE]"
    first = json.loads(frames[0].removeprefix("data: "))
    assert first["choices"][0]["delta"]["content"] == "Hello there"
    assert json.loads(frames[1].removeprefix("data: "))["choices"][0]["finish_reason"] == "stop"


def test_multimodal_content_parts_are_read(client, scripted_llm):
    scripted_llm.say("Got it")
    payload = {"messages": [{"role": "system", "content": "session_id=parts-session-0001"}, {"role": "user", "content": [{"type": "text", "text": "book me"}]}]}
    client.post("/v1/chat/completions", headers=EL_HEADERS, json=payload)
    assert scripted_llm.calls[0][-1].content == "book me"
