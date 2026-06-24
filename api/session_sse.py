"""Session-scoped SSE contract helpers.

Provides the envelope, per-session sequencing, bounded replay, and a small
in-process registry for the proposed cross-platform session event contract.
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import quote


SCHEMA_VERSION = "1.0"
STREAM_NAME = "session"

EVENT_SESSION_SNAPSHOT = "session_snapshot"
EVENT_TURN_STARTED = "turn_started"
EVENT_ACTIVITY_SUMMARY = "activity_summary"
EVENT_TURN_PROGRESS = "turn_progress"
EVENT_TURN_COMPLETED = "turn_completed"
EVENT_TURN_FAILED = "turn_failed"
EVENT_SESSION_IDLE = "session_idle"
EVENT_KEEPALIVE = "keepalive"
EVENT_APPROVAL_REQUIRED = "approval_required"
EVENT_APPROVAL_RESOLVED = "approval_resolved"
EVENT_CLARIFY_REQUIRED = "clarify_required"
EVENT_CLARIFY_RESOLVED = "clarify_resolved"

CANONICAL_EVENT_TYPES = frozenset(
    {
        EVENT_SESSION_SNAPSHOT,
        EVENT_TURN_STARTED,
        EVENT_ACTIVITY_SUMMARY,
        EVENT_TURN_PROGRESS,
        EVENT_TURN_COMPLETED,
        EVENT_TURN_FAILED,
        EVENT_SESSION_IDLE,
        EVENT_KEEPALIVE,
        EVENT_APPROVAL_REQUIRED,
        EVENT_APPROVAL_RESOLVED,
        EVENT_CLARIFY_REQUIRED,
        EVENT_CLARIFY_RESOLVED,
    }
)

# Heartbeat must satisfy the existing SSE invariant (#1623): the app heartbeat
# fires at well under half the kernel TCP keepalive window
# (KEEPIDLE 10s + KEEPINTVL 5s * KEEPCNT 3 = 25s). Every other SSE handler uses
# _SSE_HEARTBEAT_INTERVAL_SECONDS = 5; this contract inherits the same default
# so the aggregator stream cannot be torn down before its first keepalive.
DEFAULT_HEARTBEAT_SECONDS = 5
DEFAULT_REPLAY_MAX_EVENTS = 500
DEFAULT_REPLAY_MAX_SECONDS = 900

_STREAMS_LOCK = threading.Lock()
_STREAMS: dict[str, "SessionEventStream"] = {}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    try:
        value = int(str(raw).strip()) if raw is not None else int(default)
    except (TypeError, ValueError):
        value = int(default)
    return value if value > 0 else int(default)


def session_sse_enabled() -> bool:
    raw = os.getenv("HERMES_WEBUI_SESSION_SSE_ENABLED", "")
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def session_sse_heartbeat_seconds() -> int:
    return _env_int("HERMES_WEBUI_SESSION_SSE_HEARTBEAT_SECONDS", DEFAULT_HEARTBEAT_SECONDS)


def session_sse_replay_max_events() -> int:
    return _env_int("HERMES_WEBUI_SESSION_SSE_REPLAY_MAX_EVENTS", DEFAULT_REPLAY_MAX_EVENTS)


def session_sse_replay_max_seconds() -> int:
    return _env_int("HERMES_WEBUI_SESSION_SSE_REPLAY_MAX_SECONDS", DEFAULT_REPLAY_MAX_SECONDS)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def session_route(session_id: str) -> str:
    return f"/session/{quote(str(session_id or '').strip(), safe='')}"


def _trim_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _latest_assistant_summary(done_payload: dict[str, Any]) -> str:
    session = done_payload.get("session") if isinstance(done_payload, dict) else None
    messages = session.get("messages") if isinstance(session, dict) else None
    if not isinstance(messages, list):
        return ""
    for message in reversed(messages):
        if not isinstance(message, dict):
            continue
        if str(message.get("role") or "") != "assistant":
            continue
        content = _trim_text(message.get("content") or "", 240)
        if content:
            return content
    return ""


def legacy_session_event_to_contract(session_id: str, stream_id: str, event: str, data: Any) -> list[tuple[str, dict[str, Any]]]:
    payload = dict(data) if isinstance(data, dict) else {}
    route = session_route(session_id)
    normalized_event = str(event or "").strip()
    if not normalized_event:
        return []

    if normalized_event == "interim_assistant":
        text = _trim_text(payload.get("text") or "", 240)
        if not text or payload.get("already_streamed"):
            return []
        return [
            (
                EVENT_ACTIVITY_SUMMARY,
                {
                    "route": route,
                    "stream_id": stream_id,
                    "summary": text,
                    "stage": "responding",
                },
            )
        ]

    if normalized_event == "reasoning":
        text = _trim_text(payload.get("text") or "", 2000)
        if not text:
            return []
        return [
            (
                EVENT_TURN_PROGRESS,
                {
                    "route": route,
                    "stream_id": stream_id,
                    "kind": "thinking",
                    "content": text,
                    "index": 0,
                },
            )
        ]

    if normalized_event == "tool":
        name = _trim_text(payload.get("name") or "tool", 120)
        preview = _trim_text(payload.get("preview") or name, 240)
        return [
            (
                EVENT_ACTIVITY_SUMMARY,
                {
                    "route": route,
                    "stream_id": stream_id,
                    "summary": f"Running {name}",
                    "stage": "tooling",
                    "progress_hint": preview,
                },
            ),
            (
                EVENT_TURN_PROGRESS,
                {
                    "route": route,
                    "stream_id": stream_id,
                    "kind": "tool_call",
                    "content": preview,
                    "index": 0,
                },
            ),
        ]

    if normalized_event == "tool_complete":
        name = _trim_text(payload.get("name") or "tool", 120)
        preview = _trim_text(payload.get("preview") or name, 240)
        return [
            (
                EVENT_ACTIVITY_SUMMARY,
                {
                    "route": route,
                    "stream_id": stream_id,
                    "summary": f"Completed {name}",
                    "stage": "finalizing",
                    "progress_hint": preview,
                },
            ),
            (
                EVENT_TURN_PROGRESS,
                {
                    "route": route,
                    "stream_id": stream_id,
                    "kind": "tool_result",
                    "content": preview,
                    "index": 0,
                },
            ),
        ]

    if normalized_event == "done":
        terminal_payload = {
            "route": route,
            "stream_id": stream_id,
            "status": "success",
        }
        summary = _latest_assistant_summary(payload)
        if summary:
            terminal_payload["output_summary"] = summary
        terminal_state = str(payload.get("terminal_state") or "").strip()
        if terminal_state:
            terminal_payload["terminal_state"] = terminal_state
        terminal_reason = str(payload.get("terminal_reason") or "").strip()
        if terminal_reason:
            terminal_payload["terminal_reason"] = terminal_reason
        return [
            (EVENT_TURN_COMPLETED, terminal_payload),
            (
                EVENT_SESSION_IDLE,
                {
                    "route": route,
                    "stream_id": stream_id,
                    "reason": "turn_settled",
                },
            ),
        ]

    if normalized_event == "cancel":
        message = _trim_text(payload.get("message") or "Cancelled by user", 240)
        return [
            (
                EVENT_TURN_FAILED,
                {
                    "route": route,
                    "stream_id": stream_id,
                    "status": "error",
                    "error": {
                        "code": "cancelled",
                        "message": message,
                        "retryable": False,
                    },
                },
            ),
            (
                EVENT_SESSION_IDLE,
                {
                    "route": route,
                    "stream_id": stream_id,
                    "reason": "manual_stop",
                },
            ),
        ]

    if normalized_event == "apperror":
        error_code = _trim_text(payload.get("type") or "error", 80) or "error"
        message = _trim_text(payload.get("message") or "Unknown error", 240)
        retryable = error_code not in {"cancelled", "interrupted", "auth", "forbidden"}
        return [
            (
                EVENT_TURN_FAILED,
                {
                    "route": route,
                    "stream_id": stream_id,
                    "status": "error",
                    "error": {
                        "code": error_code,
                        "message": message,
                        "retryable": retryable,
                    },
                },
            ),
            (
                EVENT_SESSION_IDLE,
                {
                    "route": route,
                    "stream_id": stream_id,
                    "reason": "turn_settled",
                },
            ),
        ]

    return []


def _new_event_id(session_id: str, sequence: int) -> str:
    return f"{session_id}:{sequence}:{uuid.uuid4().hex[:12]}"


def _validate_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    return dict(payload)


def build_session_event_envelope(
    session_id: str,
    event_type: str,
    payload: dict[str, Any],
    *,
    sequence: int,
    event_id: Optional[str] = None,
    turn_id: Optional[str] = None,
    meta: Optional[dict[str, Any]] = None,
    ts: Optional[str] = None,
) -> dict[str, Any]:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        raise ValueError("session_id is required")
    normalized_event_type = str(event_type or "").strip()
    if not normalized_event_type:
        raise ValueError("event_type is required")
    if sequence < 0:
        raise ValueError("sequence must be >= 0")
    data = {
        "schema_version": SCHEMA_VERSION,
        "stream": STREAM_NAME,
        "session_id": normalized_session_id,
        "event_type": normalized_event_type,
        "event_id": str(event_id or _new_event_id(normalized_session_id, sequence)),
        "sequence": int(sequence),
        "ts": str(ts or _utc_now_iso()),
        "payload": _validate_payload(payload),
    }
    normalized_turn_id = str(turn_id or "").strip()
    if normalized_turn_id:
        data["turn_id"] = normalized_turn_id
    normalized_meta = dict(meta or {})
    if normalized_meta:
        data["meta"] = normalized_meta
    return data


def validate_session_event_envelope(envelope: Any) -> dict[str, Any]:
    if not isinstance(envelope, dict):
        raise ValueError("envelope must be an object")
    required = (
        "schema_version",
        "stream",
        "session_id",
        "event_type",
        "event_id",
        "sequence",
        "ts",
        "payload",
    )
    for key in required:
        if key not in envelope:
            raise ValueError(f"missing required field: {key}")
    if envelope.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported schema_version")
    if envelope.get("stream") != STREAM_NAME:
        raise ValueError("unsupported stream")
    if not isinstance(envelope.get("session_id"), str) or not envelope.get("session_id").strip():
        raise ValueError("session_id must be a non-empty string")
    if not isinstance(envelope.get("event_type"), str) or not envelope.get("event_type").strip():
        raise ValueError("event_type must be a non-empty string")
    if not isinstance(envelope.get("event_id"), str) or not envelope.get("event_id").strip():
        raise ValueError("event_id must be a non-empty string")
    sequence = envelope.get("sequence")
    if not isinstance(sequence, int) or sequence < 0:
        raise ValueError("sequence must be a non-negative integer")
    if not isinstance(envelope.get("ts"), str) or not envelope.get("ts").strip():
        raise ValueError("ts must be a non-empty string")
    _validate_payload(envelope.get("payload"))
    meta = envelope.get("meta")
    if meta is not None and not isinstance(meta, dict):
        raise ValueError("meta must be an object when present")
    turn_id = envelope.get("turn_id")
    if turn_id is not None and not isinstance(turn_id, str):
        raise ValueError("turn_id must be a string when present")
    return dict(envelope)


def format_sse_frame(event_name: str, envelope: dict[str, Any]) -> bytes:
    validated = validate_session_event_envelope(envelope)
    event_id = validated["event_id"]
    payload = json.dumps(validated, ensure_ascii=False)
    return f"id: {event_id}\nevent: {event_name}\ndata: {payload}\n\n".encode("utf-8")


class SessionEventStream:
    def __init__(self, session_id: str):
        self.session_id = str(session_id)
        self._lock = threading.Lock()
        self._sequence = 0
        self._subscribers: list[queue.Queue] = []
        self._replay: deque[dict[str, Any]] = deque()

    def subscribe(self, maxsize: int = 64) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=maxsize)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            try:
                self._subscribers.remove(q)
            except ValueError:
                pass

    def publish(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        turn_id: Optional[str] = None,
        meta: Optional[dict[str, Any]] = None,
        event_name: Optional[str] = None,
    ) -> dict[str, Any]:
        with self._lock:
            self._sequence += 1
            envelope = build_session_event_envelope(
                self.session_id,
                event_type,
                payload,
                sequence=self._sequence,
                turn_id=turn_id,
                meta=meta,
            )
            self._append_replay_locked(envelope)
            subscribers = list(self._subscribers)
        emit_name = str(event_name or event_type)
        for q in subscribers:
            try:
                q.put_nowait((emit_name, dict(envelope)))
            except queue.Full:
                continue
        return envelope

    def latest_sequence(self) -> int:
        with self._lock:
            return self._sequence

    def replay_after(self, event_id: Optional[str]) -> tuple[bool, list[dict[str, Any]]]:
        normalized_event_id = str(event_id or "").strip()
        with self._lock:
            self._trim_replay_locked()
            replay = [dict(item) for item in self._replay]
        if not normalized_event_id:
            return False, replay
        for idx, item in enumerate(replay):
            if item.get("event_id") == normalized_event_id:
                return True, replay[idx + 1 :]
        return False, []

    def snapshot_envelope(self, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        latest_sequence = self.latest_sequence()
        return build_session_event_envelope(
            self.session_id,
            EVENT_SESSION_SNAPSHOT,
            payload or {"latest_sequence": latest_sequence},
            sequence=latest_sequence,
        )

    def _append_replay_locked(self, envelope: dict[str, Any]) -> None:
        self._replay.append(dict(envelope))
        self._trim_replay_locked()

    def _trim_replay_locked(self) -> None:
        max_events = session_sse_replay_max_events()
        max_age = session_sse_replay_max_seconds()
        while len(self._replay) > max_events:
            self._replay.popleft()
        cutoff = time.time() - max_age
        while self._replay:
            ts = self._replay[0].get("ts")
            try:
                created = datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
            except Exception:
                break
            if created >= cutoff:
                break
            self._replay.popleft()


def get_or_create_session_event_stream(session_id: str) -> SessionEventStream:
    normalized = str(session_id or "").strip()
    if not normalized:
        raise ValueError("session_id is required")
    with _STREAMS_LOCK:
        stream = _STREAMS.get(normalized)
        if stream is None:
            stream = SessionEventStream(normalized)
            _STREAMS[normalized] = stream
        return stream


def get_session_event_stream(session_id: str) -> Optional[SessionEventStream]:
    normalized = str(session_id or "").strip()
    if not normalized:
        return None
    with _STREAMS_LOCK:
        return _STREAMS.get(normalized)


def publish_session_event(
    session_id: str,
    event_type: str,
    payload: dict[str, Any],
    *,
    turn_id: Optional[str] = None,
    meta: Optional[dict[str, Any]] = None,
    event_name: Optional[str] = None,
) -> dict[str, Any]:
    stream = get_or_create_session_event_stream(session_id)
    return stream.publish(
        event_type,
        payload,
        turn_id=turn_id,
        meta=meta,
        event_name=event_name,
    )