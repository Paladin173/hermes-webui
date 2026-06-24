from api import clarify, route_approvals, routes, session_sse


def test_approval_submit_pending_emits_approval_required(monkeypatch):
    captured = []
    sid = "sess-approval-required"
    route_approvals._pending.pop(sid, None)

    def fake_publish(session_id, event_type, payload, **kwargs):
        captured.append((session_id, event_type, payload, kwargs))

    monkeypatch.setattr(session_sse, "publish_session_event", fake_publish)
    monkeypatch.setattr(route_approvals, "publish_session_list_changed", lambda *_args, **_kwargs: None)

    try:
        route_approvals.submit_pending(
            sid,
            {
                "command": "touch /tmp/demo",
                "description": "Allow write access?",
                "pattern_key": "demo",
                "pattern_keys": ["demo"],
            },
        )
    finally:
        route_approvals._pending.pop(sid, None)

    assert captured
    session_id, event_type, payload, kwargs = captured[0]
    assert session_id == sid
    assert event_type == session_sse.EVENT_APPROVAL_REQUIRED
    assert payload["route"] == f"/session/{sid}"
    assert payload["description"] == "Allow write access?"
    assert payload["pending_count"] == 1
    assert kwargs["event_name"] == session_sse.EVENT_APPROVAL_REQUIRED


def test_resolve_approval_legacy_emits_approval_resolved(monkeypatch):
    captured = []
    sid = "sess-approval-resolved"
    approval_id = "approval-123"
    routes._pending[sid] = [{"approval_id": approval_id, "pattern_key": "demo", "pattern_keys": ["demo"]}]

    monkeypatch.setattr(session_sse, "publish_session_event", lambda *args, **kwargs: captured.append((args, kwargs)))
    monkeypatch.setattr(routes, "approve_session", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(routes, "approve_permanent", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(routes, "save_permanent_allowlist", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(routes, "resolve_gateway_approval", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(routes, "publish_session_list_changed", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(routes, "_approval_sse_notify_locked", lambda *_args, **_kwargs: None)

    try:
        resolved = routes._resolve_approval_legacy(sid, approval_id, "once")
    finally:
        routes._pending.pop(sid, None)

    assert resolved is True
    assert captured
    args, kwargs = captured[0]
    assert args[0] == sid
    assert args[1] == session_sse.EVENT_APPROVAL_RESOLVED
    assert args[2]["approval_id"] == approval_id
    assert args[2]["choice"] == "once"
    assert args[2]["pending_count"] == 0
    assert kwargs["event_name"] == session_sse.EVENT_APPROVAL_RESOLVED


def test_clarify_submit_and_resolve_emit_contract_events(monkeypatch):
    captured = []
    sid = "sess-clarify-contract"

    def fake_publish(session_id, event_type, payload, **kwargs):
        captured.append((session_id, event_type, payload, kwargs))

    monkeypatch.setattr(session_sse, "publish_session_event", fake_publish)
    monkeypatch.setattr(clarify, "publish_session_list_changed", lambda *_args, **_kwargs: None)

    try:
        entry = clarify.submit_pending(
            sid,
            {
                "question": "Choose a deployment target",
                "choices_offered": ["staging", "prod"],
            },
        )
        assert entry.clarify_id
        required = captured[0]
        assert required[1] == session_sse.EVENT_CLARIFY_REQUIRED
        assert required[2]["clarify_id"] == entry.clarify_id
        assert required[2]["pending_count"] == 1

        resolved = clarify.resolve_clarify_by_id(sid, entry.clarify_id, "staging")
        assert resolved is True
        resolved_event = captured[-1]
        assert resolved_event[1] == session_sse.EVENT_CLARIFY_RESOLVED
        assert resolved_event[2]["clarify_id"] == entry.clarify_id
        assert resolved_event[2]["response"] == "staging"
        assert resolved_event[2]["pending_count"] == 0
    finally:
        clarify.clear_pending(sid)