from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_session_sse_client_parser_is_loaded_by_app_shell():
    html = (REPO_ROOT / "static" / "index.html").read_text(encoding="utf-8")
    assert 'static/session_sse.js?v=__WEBUI_VERSION__' in html


def test_session_sse_client_parser_exports_validation_and_tracker_helpers():
    js = (REPO_ROOT / "static" / "session_sse.js").read_text(encoding="utf-8")
    assert 'function validateSessionEventEnvelope' in js
    assert 'function createSessionEventTracker' in js
    assert 'global.HermesSessionSSE = Object.freeze' in js
    assert "status:'duplicate'" in js
    assert "status:'stale'" in js
    assert "status:'applied'" in js