You are working in the `hermes-webui` repository.

Goal:
Design and implement an approval-ready, cross-platform, session-scoped SSE contract for real-time session updates. This must support Android background/reconnect use cases, but the design must be platform-neutral and clearly beneficial to web/desktop/CLI consumers as well.

Context:
- Android wrapper work is blocked until WebUI defines a stable SSE event contract (e.g., `activity_summary`, `turn_started`, etc.).
- We need a precise, versioned, resumable protocol with explicit semantics.
- This must be easy to configure by operators and easy for clients to consume.
- Do not build Android-specific protocol behavior. Build a generic contract that Android can consume.

Deliverables (required):
1. RFC/spec document (new file) describing:
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
2. Server implementation for SSE stream endpoint(s), feature-flagged.
3. Minimal client reference parser in web code (or shared util) that:
   - validates envelope
   - handles ordering + dedupe
   - handles reconnect with `Last-Event-ID`
4. Tests:
   - unit tests for event serialization and validation
   - integration tests for stream ordering, reconnect, resume, and heartbeat
   - regression tests for malformed payloads and auth failures
5. Documentation updates:
   - operator configuration
   - client integration guide
   - migration/rollout plan
6. PR description text that is approval-ready:
   - problem statement
   - design decisions + alternatives considered
   - why this helps more than Android
   - risk assessment + rollout plan

Non-goals:
- Full UI redesign.
- Android repo changes.
- Breaking existing APIs without migration/fallback.

---

## Required contract design (must implement unless impossible; if impossible, explain exactly why and propose equivalent)

### A) Endpoint and transport
- SSE endpoint should be session-scoped (example shape; adjust to project conventions):
  - `GET /api/sessions/{session_id}/events`
- Response:
  - `Content-Type: text/event-stream`
  - no buffering/caching suitable for SSE
- Auth:
  - same auth model as existing protected session APIs
  - unauthorized requests fail with standard auth error

### B) Event envelope (canonical schema)
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

Requirements:
schema_version: required, semantic version for envelope contract.
event_id: required, unique within stream; used for resume/dedupe.
sequence: required, monotonically increasing integer per session stream.
payload: required object; event-specific schema.
Unknown fields must be ignored by clients (forward compatibility).
C) Canonical event types (Phase 1)
Define and implement these event types with strict payload schema docs and examples:
session_snapshot
initial state snapshot for new subscribers or reconnect without replay
turn_started
marks beginning of a turn
activity_summary
compact summary updates intended for low-bandwidth/background consumers
turn_progress (or equivalent existing name)
incremental progress updates (optional verbosity)
turn_completed
turn terminal success state
turn_failed
turn terminal failure with structured error payload
session_idle (optional if model supports)
explicit quiescent state
keepalive
periodic liveness event or SSE comment strategy (choose one and justify)
If existing names differ, map them and document canonical naming + aliases/deprecation strategy.
D) Ordering, delivery, and resume semantics
Must define exactly:
Ordering guarantee: in-order by sequence within a single session stream.
Delivery semantics: at-least-once (clients must dedupe by event_id).
Resume behavior:
honor Last-Event-ID if provided
replay from next event if retained
if not retained, emit session_snapshot then continue live
Replay retention window:
configurable (time-based and/or count-based)
documented defaults and operator impact
E) Configurability (easy to operate)
Add server-side config with sane defaults and docs:
enable/disable stream feature flag
heartbeat interval
replay retention (count/time)
max payload size for summary/progress events
verbosity mode:
minimal (snapshot + start + summary + terminal)
full (includes progress/tool-level details if available)
optional request-level controls (query params), e.g.:
?verbosity=minimal|full
?since=<event_id> (if supported in addition to Last-Event-ID)
?events=turn_started,activity_summary,... filtering (optional but preferred)
Config must be safe by default and not expose sensitive data unexpectedly.
F) Security and privacy
No secrets/tokens/raw credentials in event payloads.
Error payloads must be structured and sanitized.
Ensure cross-origin/security behavior matches current backend policy.
Rate-limit or protect endpoints from misuse where applicable.
G) Cross-platform justification (must be explicit in docs)
In RFC and PR text, explicitly explain benefits for:
Android background reconnect continuity
Web multi-tab synchronization
Desktop wrappers/electron/TWA-like hosts
CLI/agent observers and test harnesses
Future notification/tray and activity feed consumers
H) Backward compatibility and rollout
Feature flag default off (or project-standard rollout default; justify).
No breaking changes to existing polling/live mechanisms until migration plan exists.
Provide migration path and deprecation stages:
opt-in
dual-path
preferred
deprecate legacy (future)
 
Acceptance criteria (must all pass)
RFC/spec is complete, internally consistent, and includes examples for every event type.
Endpoint emits valid SSE and valid envelope JSON for each event.
Reconnect with Last-Event-ID resumes correctly with dedupe-safe semantics.
At least one integration test simulates disconnect/reconnect and validates no duplicated application state.
Config knobs are implemented, documented, and have safe defaults.
PR includes explicit “why this is cross-platform” section and alternatives considered.
No Android-specific coupling in protocol primitives.
 
Implementation instructions
First inspect existing real-time/session code paths and naming.
Reuse existing domain language where reasonable; avoid gratuitous renames.
If introducing new names, include compatibility mapping and deprecation notes.
Keep patches focused and incremental.
Add concise code comments only where behavior is non-obvious.
If any requirement conflicts with current architecture, document tradeoffs and propose the least-disruptive alternative.
 
Output format from Codex
Return:
File-by-file change list.
Full RFC text.
Test plan + actual tests added.
Open questions requiring maintainer decision.
Final PR body draft ready to paste into GitHub.