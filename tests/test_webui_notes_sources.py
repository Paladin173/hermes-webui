"""Regression tests for WebUI notes source discovery."""
from __future__ import annotations


def test_notes_sources_identifies_note_or_knowledge_mcp_servers():
    from api.routes import _notes_sources_from_mcp_inventory

    servers = {
        "joplin": {"name": "joplin", "enabled": True, "active": True, "status": "healthy"},
        "filesystem": {"name": "filesystem", "enabled": True, "active": True, "status": "healthy"},
        "llm-wiki": {"name": "llm-wiki", "enabled": True, "active": False, "status": "configured"},
    }
    tools = [
        {"server": "joplin", "name": "search_notes", "description": "Search notes by keyword"},
        {"server": "joplin", "name": "get_note", "description": "Get full note content"},
        {"server": "filesystem", "name": "read_text_file", "description": "Read files"},
        {"server": "llm-wiki", "name": "query_knowledge_base", "description": "Search wiki knowledge"},
    ]

    sources = _notes_sources_from_mcp_inventory(servers, tools)

    assert [source["name"] for source in sources] == ["joplin", "llm-wiki"]
    assert sources[0]["label"] == "Joplin"
    assert sources[0]["tool_count"] == 2
    assert sources[0]["active"] is True
    assert sources[1]["active"] is False


def test_notes_sources_redacts_tool_descriptions_and_omits_plain_file_tools():
    from api.routes import _notes_sources_from_mcp_inventory

    servers = {"notion": {"name": "notion", "enabled": True, "active": True, "status": "healthy"}}
    tools = [
        {"server": "notion", "name": "search_pages", "description": "Search notes token=abc123SECRET"},
    ]

    [source] = _notes_sources_from_mcp_inventory(servers, tools)

    assert source["name"] == "notion"
    assert "token" not in source["tools"][0]["description"].lower()
    assert "[REDACTED]" in source["tools"][0]["description"]


def test_notes_sources_shows_configured_note_servers_without_tool_inventory():
    from api.routes import _notes_sources_from_mcp_inventory

    servers = {
        "joplin": {"name": "joplin", "enabled": True, "active": False, "status": "configured"},
        "filesystem": {"name": "filesystem", "enabled": True, "active": True, "status": "healthy"},
    }

    sources = _notes_sources_from_mcp_inventory(servers, [])

    assert [source["name"] for source in sources] == ["joplin"]
    assert sources[0]["label"] == "Joplin"
    assert sources[0]["tool_count"] == 3
    assert [tool["name"] for tool in sources[0]["tools"]] == ["search_notes", "list_notes", "get_note"]
    assert all(tool.get("inferred") is True for tool in sources[0]["tools"])
    assert sources[0]["tool_source"] == "configured_hint"
    assert sources[0]["status"] == "configured"


def test_joplin_search_notes_returns_safe_snippets(monkeypatch):
    from api import routes

    def fake_get(path, params=None):
        assert path == "/search"
        assert params["type"] == "note"
        return {"items": [{
            "id": "abc123def4567890",
            "title": "Hermes Context",
            "body": "This is a long Hermes context note with useful details.",
            "parent_id": "folder123",
            "updated_time": 123,
        }]}

    monkeypatch.setattr(routes, "_joplin_api_get", fake_get)

    results = routes._joplin_search_notes("Hermes")

    assert results == [{
        "id": "abc123def4567890",
        "title": "Hermes Context",
        "snippet": "This is a long Hermes context note with useful details.",
        "parent_id": "folder123",
        "updated_time": 123,
        "source": "joplin",
    }]


def test_joplin_get_note_validates_id_and_truncates_body(monkeypatch):
    from api import routes

    def fake_get(path, params=None):
        assert path == "/notes/abc123def4567890"
        return {
            "id": "abc123def4567890",
            "title": "Big Note",
            "body": "x" * 60000,
            "parent_id": "folder123",
            "updated_time": 456,
            "created_time": 123,
        }

    monkeypatch.setattr(routes, "_joplin_api_get", fake_get)

    note = routes._joplin_get_note("abc123def4567890")

    assert note["title"] == "Big Note"
    assert note["source"] == "joplin"
    assert len(note["body"]) < 51000
    assert "Preview truncated" in note["body"]
