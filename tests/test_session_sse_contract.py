import json

import pytest

from api import session_sse


def test_build_and_validate_session_event_envelope_round_trips():
    envelope = session_sse.build_session_event_envelope(
        "sess-1",
        session_sse.EVENT_TURN_STARTED,
        {"turn_id": "turn-1", "actor": "user"},
        sequence=1,
        turn_id="turn-1",
        meta={"source": "test"},
        event_id="evt-1",
        ts="2026-06-23T12:34:56.789Z",
    )

    validated = session_sse.validate_session_event_envelope(envelope)

    assert validated["schema_version"] == "1.0"
    assert validated["stream"] == "session"
    assert validated["session_id"] == "sess-1"
    assert validated["event_type"] == session_sse.EVENT_TURN_STARTED
    assert validated["event_id"] == "evt-1"
    assert validated["sequence"] == 1
    assert validated["turn_id"] == "turn-1"
    assert validated["payload"] == {"turn_id": "turn-1", "actor": "user"}
    assert validated["meta"] == {"source": "test"}


def test_validate_session_event_envelope_rejects_invalid_payload_shape():
    with pytest.raises(ValueError, match="payload must be an object"):
        session_sse.build_session_event_envelope(
            "sess-1",
            session_sse.EVENT_ACTIVITY_SUMMARY,
            ["not", "an", "object"],
            sequence=1,
        )


def test_format_sse_frame_emits_id_event_and_json_payload():
    envelope = session_sse.build_session_event_envelope(
        "sess-2",
        session_sse.EVENT_KEEPALIVE,
        {"server_time": "2026-06-23T12:35:12.100Z"},
        sequence=2,
        event_id="evt-keepalive",
        ts="2026-06-23T12:35:12.100Z",
    )

    frame = session_sse.format_sse_frame(session_sse.EVENT_KEEPALIVE, envelope).decode("utf-8")

    assert frame.startswith("id: evt-keepalive\nevent: keepalive\ndata: ")
    payload = frame.split("data: ", 1)[1].strip()
    decoded = json.loads(payload)
    assert decoded["event_id"] == "evt-keepalive"
    assert decoded["event_type"] == session_sse.EVENT_KEEPALIVE


def test_session_event_stream_publish_increments_sequence_and_replays_after_event_id(monkeypatch):
    monkeypatch.setenv("HERMES_WEBUI_SESSION_SSE_REPLAY_MAX_EVENTS", "10")
    monkeypatch.setenv("HERMES_WEBUI_SESSION_SSE_REPLAY_MAX_SECONDS", "3600")
    stream = session_sse.SessionEventStream("sess-3")
    q = stream.subscribe()
    try:
        first = stream.publish(session_sse.EVENT_TURN_STARTED, {"actor": "user"}, event_name="turn_started")
        second = stream.publish(session_sse.EVENT_ACTIVITY_SUMMARY, {"summary": "Planning"}, event_name="activity_summary")

        assert first["sequence"] == 1
        assert second["sequence"] == 2
        assert q.get_nowait()[1]["event_id"] == first["event_id"]
        assert q.get_nowait()[1]["event_id"] == second["event_id"]

        found, replay = stream.replay_after(first["event_id"])
        assert found is True
        assert [item["event_id"] for item in replay] == [second["event_id"]]
    finally:
        stream.unsubscribe(q)


def test_session_event_stream_replay_after_missing_id_returns_snapshot_fallback_signal(monkeypatch):
    monkeypatch.setenv("HERMES_WEBUI_SESSION_SSE_REPLAY_MAX_EVENTS", "10")
    monkeypatch.setenv("HERMES_WEBUI_SESSION_SSE_REPLAY_MAX_SECONDS", "3600")
    stream = session_sse.SessionEventStream("sess-4")
    stream.publish(session_sse.EVENT_TURN_COMPLETED, {"status": "success"}, event_name="turn_completed")

    found, replay = stream.replay_after("missing-event")

    assert found is False
    assert replay == []
    snapshot = stream.snapshot_envelope({"latest_sequence": stream.latest_sequence(), "run_state": "completed"})
    assert snapshot["event_type"] == session_sse.EVENT_SESSION_SNAPSHOT
    assert snapshot["payload"]["latest_sequence"] == 1


def test_session_route_helper_uses_canonical_session_path():
    assert session_sse.session_route("sess 5") == "/session/sess%205"


def test_legacy_interim_assistant_maps_to_activity_summary():
    mapped = session_sse.legacy_session_event_to_contract(
        "sess-legacy",
        "stream-1",
        "interim_assistant",
        {"text": "Working through the migration now.", "already_streamed": False},
    )

    assert mapped == [
        (
            session_sse.EVENT_ACTIVITY_SUMMARY,
            {
                "route": "/session/sess-legacy",
                "stream_id": "stream-1",
                "summary": "Working through the migration now.",
                "stage": "responding",
            },
        )
    ]


def test_legacy_tool_event_maps_to_summary_and_progress():
    mapped = session_sse.legacy_session_event_to_contract(
        "sess-legacy",
        "stream-2",
        "tool",
        {"name": "apply_patch", "preview": "Updating session contract"},
    )

    assert mapped[0][0] == session_sse.EVENT_ACTIVITY_SUMMARY
    assert mapped[0][1]["summary"] == "Running apply_patch"
    assert mapped[1][0] == session_sse.EVENT_TURN_PROGRESS
    assert mapped[1][1]["kind"] == "tool_call"


def test_legacy_done_maps_to_turn_completed_and_session_idle():
    mapped = session_sse.legacy_session_event_to_contract(
        "sess-legacy",
        "stream-3",
        "done",
        {
            "session": {
                "messages": [
                    {"role": "user", "content": "hello"},
                    {"role": "assistant", "content": "Finished the migration and updated tests."},
                ]
            },
            "terminal_state": "tool_limit_reached",
            "terminal_reason": "max_iterations",
        },
    )

    assert mapped[0][0] == session_sse.EVENT_TURN_COMPLETED
    assert mapped[0][1]["output_summary"] == "Finished the migration and updated tests."
    assert mapped[0][1]["terminal_state"] == "tool_limit_reached"
    assert mapped[1][0] == session_sse.EVENT_SESSION_IDLE


def test_legacy_apperror_maps_to_turn_failed_and_session_idle():
    mapped = session_sse.legacy_session_event_to_contract(
        "sess-legacy",
        "stream-4",
        "apperror",
        {"type": "rate_limit", "message": "Provider rate limited the request."},
    )

    assert mapped[0][0] == session_sse.EVENT_TURN_FAILED
    assert mapped[0][1]["error"]["code"] == "rate_limit"
    assert mapped[0][1]["error"]["retryable"] is True
    assert mapped[1][0] == session_sse.EVENT_SESSION_IDLE