# Session SSE Contract v1 Implementation Brief

- **Status:** Working draft
- **Related RFC:** [session-sse-contract-v1.md](session-sse-contract-v1.md)
- **Related Issue:** #4812
- **Created:** 2026-06-23

You are working in the `hermes-webui` repository.

## Goal

Design and implement an approval-ready, cross-platform, session-scoped SSE
contract for real-time session updates. This must support Android background /
reconnect use cases, but the design must be platform-neutral and clearly
beneficial to web/desktop/CLI consumers as well.

## Context

- Android wrapper work is blocked until WebUI defines a stable SSE event
  contract (for example `activity_summary`, `turn_started`, and related
  lifecycle events).
- We need a precise, versioned, resumable protocol with explicit semantics.
- This must be easy to configure by operators and easy for clients to consume.
- Do not build Android-specific protocol behavior. Build a generic contract
  that Android can consume.

## Deliverables

### 1. RFC/spec document

Create or update the RFC/spec to describe:

- endpoint shape
- auth model
- event envelope schema
- canonical event types
- ordering and idempotency semantics
- reconnect/resume semantics (`id`, `Last-Event-ID`)
- heartbeat/keepalive behavior
- error and terminal-state events
- compatibility/versioning strategy
- configuration knobs (server + request level)

### 2. Server implementation

- Add feature-flagged SSE stream endpoint(s).

### 3. Minimal client reference parser

- Validate the envelope.
- Handle ordering and dedupe.
- Handle reconnect with `Last-Event-ID`.

### 4. Tests

- Unit tests for event serialization and validation.
- Integration tests for stream ordering, reconnect, resume, and heartbeat.
- Regression tests for malformed payloads and auth failures.

### 5. Documentation updates

- Operator configuration.
- Client integration guide.
- Migration/rollout plan.

### 6. PR description text

- Problem statement.
- Design decisions and alternatives considered.
- Why this helps more than Android.
- Risk assessment and rollout plan.

## Non-goals

- Full UI redesign.
- Android repo changes.
- Breaking existing APIs without migration/fallback.

## Required Contract Design

### A. Endpoint and transport

- SSE endpoint should be session-scoped, for example:
  - `GET /api/sessions/{session_id}/events`
- Response:
  - `Content-Type: text/event-stream`
  - no buffering/caching suitable for SSE
- Auth:
  - same auth model as existing protected session APIs
  - unauthorized requests fail with standard auth error

### B. Event envelope

All non-comment SSE messages must carry JSON with this top-level envelope:

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

Requirements:

- `schema_version`: required, semantic version for envelope contract.
- `event_id`: required, unique within stream; used for resume/dedupe.
- `sequence`: required, monotonically increasing integer per session stream.
- `payload`: required object; event-specific schema.
- Unknown fields must be ignored by clients for forward compatibility.

### C. Canonical event types (Phase 1)

Define and implement these event types with strict payload schema docs and
examples:

- `session_snapshot`
  - initial state snapshot for new subscribers or reconnect without replay
- `turn_started`
  - marks beginning of a turn
- `activity_summary`
  - compact summary updates intended for low-bandwidth/background consumers
- `turn_progress`
  - incremental progress updates (or equivalent existing name)
- `turn_completed`
  - turn terminal success state
- `turn_failed`
  - turn terminal failure with structured error payload
- `session_idle`
  - optional if the model/runtime supports explicit quiescent state
- `keepalive`
  - periodic liveness event or SSE comment strategy; choose one and justify

If existing names differ, map them and document canonical naming plus
aliases/deprecation strategy.

### D. Ordering, delivery, and resume semantics

Define exactly:

- Ordering guarantee: in-order by `sequence` within a single session stream.
- Delivery semantics: at-least-once; clients must dedupe by `event_id`.
- Resume behavior:
  - honor `Last-Event-ID` if provided
  - replay from next event if retained
  - if not retained, emit `session_snapshot` then continue live
- Replay retention window:
  - configurable by time and/or count
  - documented defaults and operator impact

### E. Configurability

Add server-side config with safe defaults and docs:

- enable/disable stream feature flag
- heartbeat interval
- replay retention (count/time)
- max payload size for summary/progress events
- verbosity mode:
  - `minimal` (`snapshot + start + summary + terminal`)
  - `full` (includes progress/tool-level details if available)
- optional request-level controls:
  - `?verbosity=minimal|full`
  - `?since=<event_id>`
  - `?events=turn_started,activity_summary,...` (preferred if practical)

Config must be safe by default and must not expose sensitive data
unexpectedly.

### F. Security and privacy

- No secrets/tokens/raw credentials in event payloads.
- Error payloads must be structured and sanitized.
- Cross-origin/security behavior must match current backend policy.
- Rate-limit or otherwise protect endpoints from misuse where applicable.

### G. Cross-platform justification

The RFC and PR text must explicitly explain benefits for:

- Android background reconnect continuity
- Web multi-tab synchronization
- Desktop wrappers/electron/TWA-like hosts
- CLI/agent observers and test harnesses
- Future notification/tray and activity feed consumers

### H. Backward compatibility and rollout

- Feature flag default off unless project standard dictates otherwise and the
  justification is explicit.
- No breaking changes to existing polling/live mechanisms until a migration plan
  exists.
- Provide migration stages:
  - opt-in
  - dual-path
  - preferred
  - deprecate legacy (future)

## Acceptance Criteria

- RFC/spec is complete, internally consistent, and includes examples for every
  event type.
- Endpoint emits valid SSE and valid envelope JSON for each event.
- Reconnect with `Last-Event-ID` resumes correctly with dedupe-safe semantics.
- At least one integration test simulates disconnect/reconnect and validates no
  duplicated application state.
- Config knobs are implemented, documented, and have safe defaults.
- PR includes explicit cross-platform value and alternatives considered.
- No Android-specific coupling in protocol primitives.

## Implementation Instructions

- Inspect existing real-time/session code paths and naming first.
- Reuse existing domain language where reasonable; avoid gratuitous renames.
- If introducing new names, include compatibility mapping and deprecation
  notes.
- Keep patches focused and incremental.
- Add concise code comments only where behavior is non-obvious.
- If any requirement conflicts with the current architecture, document the
  tradeoff and propose the least-disruptive alternative.

## Expected Implementation Output

- File-by-file change list.
- Full RFC text.
- Test plan plus actual tests added.
- Open questions requiring maintainer decision.
- Final PR body draft ready to paste into GitHub.