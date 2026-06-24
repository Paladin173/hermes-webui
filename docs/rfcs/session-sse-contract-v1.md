# Session SSE Contract v1

- **Status:** Proposed
- **Author:** @Paladin173
- **Created:** 2026-06-23
- **Issue:** #4812
- **Related consumer:** hermes-android Issue 10 background activity notification flow

## Problem

Hermes WebUI currently exposes multiple real-time update paths, but there is no
single, versioned, resumable session-scoped SSE contract that clients can rely
on across disconnect/reconnect scenarios.

This blocks Android background continuity and also limits reliability for web
multi-tab, desktop wrappers, CLI observers, and future notification/activity
feed consumers.

## Goals

- Define one canonical session-scoped SSE contract with explicit semantics.
- Make reconnect/resume deterministic via `id` and `Last-Event-ID`.
- Support low-bandwidth and high-fidelity modes without changing endpoint shape.
- Keep the design platform-neutral and useful to all clients.
- Keep rollout backward-compatible with existing live/polling behavior.

## Non-goals

- Android-specific protocol branches or mobile-only fields.
- Replacing all existing real-time endpoints in one cutover.
- UI redesign.

## Normative Terms

The key words **MUST**, **SHOULD**, and **MAY** are to be interpreted as
normative requirements.

## Endpoint and Transport

### Endpoint

- `GET /api/sessions/{session_id}/events`

### Response

- `Content-Type: text/event-stream`
- `Cache-Control: no-cache`
- `Connection: keep-alive`
- Disable proxy buffering where supported.

### Auth

- Uses the same auth and session authorization model as protected session APIs.
- Unauthorized requests return the existing standardized auth error response.

### Feature Flag

- Server flag: `HERMES_WEBUI_SESSION_SSE_ENABLED`
- Default: `false` (opt-in rollout).
- When disabled, endpoint returns `404` to avoid accidental client coupling.

## Event Envelope

All non-comment SSE messages carry JSON with this envelope.

```json
{
  "schema_version": "1.0",
  "stream": "session",
  "session_id": "string",
  "event_type": "turn_started",
  "event_id": "opaque-monotonic-id",
  "sequence": 123,
  "ts": "2026-06-23T12:34:56.789Z",
  "turn_id": "optional-string",
  "payload": {},
  "meta": {
    "trace_id": "optional-string",
    "source": "optional-string"
  }
}
```

### Envelope Rules

- `schema_version` MUST be present and semantic-versioned for envelope schema.
- `stream` MUST be `session` for this contract.
- `session_id` MUST match the endpoint path.
- `event_type` MUST be one canonical event type or documented alias.
- `event_id` MUST be unique within a session stream.
- `sequence` MUST be a monotonically increasing integer per session stream.
- `ts` MUST be RFC3339 UTC timestamp with milliseconds.
- `payload` MUST be an object.
- Unknown fields MUST be ignored by clients.

### SSE Frame Mapping

- SSE `id:` MUST equal envelope `event_id`.
- SSE `event:` SHOULD equal envelope `event_type`.
- SSE `data:` MUST contain one serialized envelope JSON object.

## Canonical Event Types (Phase 1)

### `session_snapshot`

Purpose: initial state for new subscribers or reconnect when replay is
insufficient.

Payload:

```json
{
  "route": "/session/session_123",
  "latest_sequence": 128,
  "stream_id": "optional-string",
  "active_turn_id": "optional-string",
  "run_state": "idle|running|failed|completed",
  "summary": {
    "last_user_message": "optional-string",
    "last_assistant_message": "optional-string"
  }
}
```

### `turn_started`

Purpose: marks beginning of a turn.

Payload:

```json
{
  "route": "/session/session_123",
  "turn_id": "string",
  "stream_id": "string",
  "actor": "user|assistant|system",
  "input_preview": "optional-string",
  "started_at": 1761177600
}
```

### `activity_summary`

Purpose: compact progress for low-bandwidth/background consumers.

Payload:

```json
{
  "route": "/session/session_123",
  "stream_id": "string",
  "turn_id": "string",
  "summary": "string",
  "stage": "planning|tooling|responding|finalizing",
  "progress_hint": "optional-string"
}
```

### `turn_progress`

Purpose: higher-verbosity incremental progress.

Payload:

```json
{
  "route": "/session/session_123",
  "stream_id": "string",
  "turn_id": "string",
  "kind": "thinking|tool_call|tool_result|text_chunk",
  "content": "string",
  "index": 42
}
```

### `turn_completed`

Purpose: terminal success state for a turn.

Payload:

```json
{
  "route": "/session/session_123",
  "stream_id": "string",
  "turn_id": "string",
  "status": "success",
  "output_summary": "optional-string"
}
```

### `turn_failed`

Purpose: terminal failure state for a turn.

Payload:

```json
{
  "route": "/session/session_123",
  "stream_id": "string",
  "turn_id": "string",
  "status": "error",
  "error": {
    "code": "string",
    "message": "sanitized-string",
    "retryable": true
  }
}
```

### `session_idle`

Purpose: explicit quiescent session state.

Payload:

```json
{
  "route": "/session/session_123",
  "stream_id": "optional-string",
  "reason": "turn_settled|timeout|manual_stop"
}
```

### `keepalive`

Chosen strategy: explicit `keepalive` event.

Justification:

- Safer for generic clients than comment-only heartbeats.
- Easier to test, meter, and observe in logs.
- Works uniformly for browser EventSource, desktop wrappers, and CLI readers.

Payload:

```json
{
  "server_time": "2026-06-23T12:35:12.100Z"
}
```

### Optional attention events

These are optional v1 extension events for clients that need pending approval
or clarify state without polling.

### `approval_required`

Purpose: surface a pending approval prompt in a session-scoped,
notification-safe form.

Payload:

```json
{
  "route": "/session/session_123",
  "approval_id": "approval_789",
  "description": "Allow write access?",
  "choices": ["once", "session", "always", "deny"],
  "pending_count": 1
}
```

### `approval_resolved`

Purpose: tell clients that a pending approval was answered or cleared.

Payload:

```json
{
  "route": "/session/session_123",
  "approval_id": "approval_789",
  "choice": "once",
  "pending_count": 0,
  "resolved_gateway": false
}
```

### `clarify_required`

Purpose: surface a pending clarify prompt with its stable prompt id.

Payload:

```json
{
  "route": "/session/session_123",
  "clarify_id": "clarify_456",
  "question": "Choose a deployment target",
  "choices": ["staging", "prod"],
  "pending_count": 1,
  "expires_at": 1761177612
}
```

### `clarify_resolved`

Purpose: tell clients that a clarify prompt was answered or expired/cleared.

Payload:

```json
{
  "route": "/session/session_123",
  "clarify_id": "clarify_456",
  "response": "staging",
  "pending_count": 0,
  "next_clarify_id": null
}
```

Schema notes:

- `route` SHOULD be a trusted in-app session route so browser, desktop, and
  Android/native consumers can deep-link to the active session without
  rebuilding route logic client-side.
- `stream_id` SHOULD be present for turn-scoped lifecycle and progress events
  when the runtime already has one.
- Attention events are optional extensions; clients that do not implement them
  MUST ignore them like any other unknown event type.

### Canonical Naming and Alias Strategy

- Canonical names above are normative for v1.
- Legacy aliases MAY be accepted on input or emitted in compatibility mode.
- If aliases are used, server MUST emit canonical `event_type` and MAY include
  `meta.alias_of` for traceability.

Proposed alias table for implementation:

| Canonical         | Legacy Alias Candidates      | v1 Emission |
|-------------------|------------------------------|-------------|
| `turn_progress`   | `progress`, `partial_update` | canonical   |
| `activity_summary`| `activity`, `summary_update` | canonical   |

If no legacy events are found in current code paths, this table remains
documentary and no alias mode is enabled.

## Ordering, Delivery, and Resume

### Ordering

- Per-session events MUST be emitted in ascending `sequence` order.
- No ordering guarantee is made across different sessions.

### Delivery

- Semantics are at-least-once.
- Clients MUST dedupe by `event_id`.

### Resume

- Server MUST honor `Last-Event-ID` if present.
- Request param `since=<event_id>` MAY be accepted; if both are present,
  `since` takes precedence.
- If retained history contains the requested id, server replays from next event.
- If not retained, server MUST emit `session_snapshot` then continue live.

### Replay Retention

- `HERMES_WEBUI_SESSION_SSE_REPLAY_MAX_EVENTS` default `500`
- `HERMES_WEBUI_SESSION_SSE_REPLAY_MAX_SECONDS` default `900`

Retention is bounded by both count and age to cap memory while preserving
practical reconnect windows.

### Reconnect Example

1. Client receives up to sequence `120` with `event_id=e120`.
2. Connection drops.
3. Client reconnects with `Last-Event-ID: e120`.
4. Server replay buffer still contains `e120`.
5. Server emits sequence `121..N`, then live events.
6. Client discards any duplicate `event_id` already applied.

If `e120` is evicted, server emits one `session_snapshot` and then live events
with current sequence progression.

## Configurability

### Server-Level Knobs

- `HERMES_WEBUI_SESSION_SSE_ENABLED=false`
- `HERMES_WEBUI_SESSION_SSE_HEARTBEAT_SECONDS=15`
- `HERMES_WEBUI_SESSION_SSE_REPLAY_MAX_EVENTS=500`
- `HERMES_WEBUI_SESSION_SSE_REPLAY_MAX_SECONDS=900`
- `HERMES_WEBUI_SESSION_SSE_SUMMARY_MAX_BYTES=8192`
- `HERMES_WEBUI_SESSION_SSE_PROGRESS_MAX_BYTES=32768`
- `HERMES_WEBUI_SESSION_SSE_DEFAULT_VERBOSITY=minimal`

### Request-Level Controls

- `verbosity=minimal|full`
- `since=<event_id>`
- `events=turn_started,activity_summary,...`

Filtering rules:

- `session_snapshot` and `keepalive` SHOULD still be deliverable for stream
  safety unless explicitly disabled by future contract revision.
- Unknown requested event names are ignored.

### Verbosity Contract

- `minimal`: `session_snapshot`, `turn_started`, `activity_summary`,
  `turn_completed`, `turn_failed`, `session_idle`, `keepalive`
- `full`: includes all `minimal` plus `turn_progress`

## Error and Terminal Semantics

- Exactly one terminal event (`turn_completed` or `turn_failed`) MUST be emitted
  per turn.
- Terminal events MAY be replayed and MUST preserve original `event_id` and
  `sequence`.
- `session_idle` MAY follow terminal event when the runtime enters quiescence.

Error payload policy:

- `error.code`: stable machine-readable string.
- `error.message`: sanitized user-safe text.
- `error.retryable`: boolean hint.
- No stack traces, raw provider responses, tokens, keys, or credentials.

## Security and Privacy

- Payloads MUST NOT include secrets, raw credentials, auth tokens, cookies, or
  provider API keys.
- Error details MUST be sanitized.
- CORS and auth behavior MUST match existing backend policy for protected APIs.
- Endpoint SHOULD be protected against abuse using existing request limiting and
  session authorization checks.

## Compatibility and Versioning

- Envelope version starts at `schema_version=1.0`.
- Additive fields/events are minor-compatible and clients MUST ignore unknowns.
- Breaking envelope changes require a new major schema version.
- During migration, dual-path operation is expected (legacy live path plus this
  contract) until clients are upgraded.

## Cross-Platform Benefits

- Android: background reconnect with deterministic replay and dedupe.
- Android: background notifications can show concise summary text plus a trusted
  session route without consuming the raw token stream.
- Web: multi-tab synchronization and reliable resume after transient disconnect.
- Desktop wrappers: stable stream primitive for host-level notifications.
- CLI/observers: machine-parsable, versioned event stream with replay controls.
- Future tray/feed systems: normalized event model for fan-out consumers.

## Rollout Plan

1. Opt-in: feature flag off by default; internal validation only.
2. Dual-path: selected clients consume SSE contract while legacy path remains.
3. Preferred: contract becomes recommended default for new clients.
4. Deprecation planning: legacy behavior retirement proposed in a follow-up RFC.

Operational guardrails:

- Success metrics: reconnect success rate, duplicate-apply rate, replay-hit rate,
  median reconnect recovery time.
- Alerts: heartbeat timeout spikes, auth failures, malformed payload rate.
- Rollback trigger: sustained reconnect failure regression or excessive replay
  miss forcing snapshot fallback.

## Open Questions

- Should `session_snapshot` include optional compact tool-state summary in v1,
  or remain intentionally minimal?
- Should `events` filtering be available in v1 GA or guarded behind a secondary
  flag first?
- Should compatibility alias mode ever emit legacy names, or only accept them?

## Implementation Notes (Non-normative)

- Keep implementation session-scoped and platform-neutral.
- Reuse existing auth/session ownership checks.
- Avoid exposing new sensitive fields in summary/progress payloads.
- Add integration tests for disconnect/reconnect and dedupe-safe replay.