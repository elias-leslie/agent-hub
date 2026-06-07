# Agent Hub Primary Chat Contract

Status: public architecture contract

## Goal

Agent Hub owns the primary interactive agent UI and durable runtime for chat, coding, tools, artifacts, permissions, browser continuation, and session lifecycle. Other clients, including SummitFlow and browser extensions, attach to Agent Hub sessions. They do not create competing chat runtimes.

## Ownership

Agent Hub owns:

- Canonical sessions, messages, event stream, artifacts, tool calls, permissions, memory, model routing, cost and token accounting, stop/regenerate/continue, fork, compact, resume, and long-running status.
- UI for real agent work: conversation timeline, tool results, code diffs, artifacts, attachments, context visibility, model/thinking controls, project/task binding, and permission decisions.
- Durable APIs that web UI, browser extension bubble, SummitFlow, and transitional TUI adapters can use.

SummitFlow owns:

- Project and browser context bridge.
- Co-browser launch/status surfaces.
- Dedicated-profile browser pairing, page state, annotation transport, sensitive-mode enforcement, and revocation.
- Compact browser evidence transfer to Agent Hub.

SummitFlow must not own:

- Primary chat UX.
- Agent runtime policy.
- Model-visible long-term session memory.
- A second design-review chat workspace.

## Durable Session Model

The existing `sessions` and `session_events` tables remain the durable source of truth. The current ingestion contract in `docs/session-ingestion-convergence-plan.md` stays valid:

1. `upsert_session`
2. `append_normalized_events`
3. `finalize_session`

Primary chat extends that contract with a clear separation between app events and model-visible context.

### Session Fields

Required session metadata:

- `id`
- `project_id`
- `provider`
- `model`
- `session_type`
- `agent_slug`
- `external_id`
- `parent_session_id`
- `current_branch`
- `cwd` or `provider_metadata.cwd`
- `declared_scope_paths`
- `observed_read_paths`
- `observed_write_paths`
- `scope_confidence`
- `client_id`
- `request_source`
- `provider_metadata`

Additional fields can live in `provider_metadata` until they prove stable enough for columns.

### Event Classes

Agent Hub stores one append-only event stream per session.

Model events:

- `user_message`
- `assistant_message`
- `system_message`
- `thinking`
- `tool_use`
- `tool_result`
- `error`
- `subagent_result`

Runtime events:

- `session_opened`
- `session_resumed`
- `session_forked`
- `session_compacted`
- `session_closed`
- `model_changed`
- `thinking_level_changed`
- `permission_requested`
- `permission_granted`
- `permission_denied`
- `artifact_created`
- `artifact_updated`
- `attachment_added`
- `context_selected`
- `context_compacted`
- `status_updated`

Browser client events:

- `browser_page_state_updated`
- `browser_annotation_created`
- `browser_annotation_updated`
- `browser_control_requested`
- `browser_control_granted`
- `browser_control_revoked`
- `browser_user_message`
- `browser_agent_message`
- `browser_teardown`

Runtime and browser events are app-visible by default. They become model-visible only through compact context selection.

## Message Model

Agent Hub should converge on typed content blocks rather than plain strings only:

- `text`
- `thinking`
- `tool_call`
- `tool_result`
- `image_ref`
- `artifact_ref`
- `attachment_ref`
- `browser_anchor`

Rules:

- Store full app timeline in `session_events`.
- Pass only selected compact blocks to the model.
- Preserve provider provenance: provider, model, response id, tool call id, usage, stop reason.
- Keep tool-call identity stable across regenerate, continue, and fork.
- Treat screenshots, DOM extracts, replay, console, network, and large files as artifacts or attachments, not default prompt text.

## Artifacts

Artifacts are first-class session objects, not long chat messages.

Artifact types:

- code diff
- file patch
- generated file
- command output
- screenshot
- DOM extract
- browser replay
- annotation set
- design review note
- structured report

Artifact records must include:

- artifact id
- session id
- originating event id
- type
- title
- mime type or schema
- storage pointer
- summary
- visibility
- model-visible compact summary

The chat UI renders artifact cards inline, with drill-in views for large content.

## Permissions

Permission decisions are session events.

Minimum permission modes:

- `ask`
- `allow_once`
- `allow_session`
- `deny`
- `yolo`

Permission request payload:

- action
- tool or capability
- target project
- target paths or hosts
- risk summary
- requested duration
- source client
- proposed model-visible evidence

Browser grants must be short-lived, revocable from Agent Hub and SummitFlow, and visible in both clients.

## Context Selection

The model does not receive the whole app timeline.

Default model context:

- current user message
- compact relevant prior conversation
- active task and project binding
- selected files or artifacts
- current permission state
- compact tool status
- compact browser state when attached

Compact browser state:

- URL
- title
- viewport
- scroll
- selected element selector
- bbox
- annotation id
- short local text snippet
- artifact ids
- sensitive-mode state

Excluded unless explicitly requested:

- screenshots
- full DOM
- replay streams
- console logs
- network logs
- cookies
- credentials
- clipboard payloads
- normal browser profile data

## UI Requirements

Primary chat UI must support:

- streaming
- stop
- regenerate
- continue
- resume
- fork
- compact
- tool-call rendering
- tool-result rendering
- errors
- code diffs
- artifacts
- attachments
- long-running status
- project and task binding
- agent and model selection
- thinking controls
- permission prompts
- context and cost hints

The UI must not emulate a terminal as the primary experience. Terminal-like output can appear as tool output or artifacts.

## Client Contract

Agent Hub web UI:

- Full primary client.
- Can create, resume, fork, compact, and close sessions.
- Owns full timeline rendering and permission prompts.

SummitFlow:

- Launch/status client.
- Creates or links a co-browser session to an Agent Hub session.
- Sends compact browser events to Agent Hub.
- Displays session link, page state, annotations, permission state, and teardown controls.

Browser extension bubble:

- Lightweight same-session client.
- Sends user messages and annotation events to Agent Hub.
- Receives agent messages, browser callouts, artifact refs, and permission state.
- Does not persist secrets or normal profile data.

Codex, Claude Code, Jenny, and other TUIs:

- Transitional adapters.
- Translate native events into `session_events`.
- Keep provider-specific parsing thin.
- Let Agent Hub become the target UI for continuation, permissions, artifacts, and session lifecycle.

## Pi-mono Comparison

Borrow:

- Event-first runtime.
- Typed content blocks for text, thinking, tool calls, tool results, and images.
- Provider registry style with thin providers and unified stream events.
- Session tree concepts for fork, branch summary, compaction, and resume.
- Lifecycle events before switch, fork, shutdown, and start.
- Extension/client contract that sends app events without forcing every event into model context.

Avoid:

- Local JSONL as Agent Hub source of truth. Agent Hub already has durable DB sessions and events.
- Browser/TUI terminal emulation as the main UI.
- Broad plugin marketplace before the session and event contract stabilizes.
- Provider-specific artifact extraction in adapters.
- Large browser telemetry in prompt context.

Adapt:

- Pi-mono tree entries map to Agent Hub `parent_session_id`, fork metadata, and future event parent ids.
- Pi-mono custom messages map to Agent Hub app events with explicit model-visibility flags.
- Pi-mono compaction entries map to durable `session_compacted` events plus summary artifacts.
- Pi-mono provider stream maps to Agent Hub normalized stream and persisted session events.

## API Surface

Current APIs to preserve:

- `POST /api/complete`
- `POST /api/complete/cancel`
- `POST /api/sessions`
- `GET /api/sessions`
- `GET /api/sessions/{session_id}`
- `GET /api/sessions/{session_id}/events`
- `POST /api/sessions/{session_id}/events`
- `POST /api/sessions/{session_id}/fork`
- `POST /api/sessions/{session_id}/promote`
- `POST /api/sessions/{session_id}/close`
- `POST /api/session-ingestion/sessions/upsert`
- `POST /api/session-ingestion/sessions/{session_id}/transcript-events`
- `POST /api/session-ingestion/sessions/{session_id}/heartbeat`
- `POST /api/session-ingestion/sessions/{session_id}/finalize`

API gaps for next slices:

- `POST /api/sessions/{session_id}/messages`
- `POST /api/sessions/{session_id}/continue`
- `POST /api/sessions/{session_id}/compact`
- `POST /api/sessions/{session_id}/artifacts`
- `GET /api/sessions/{session_id}/artifacts`
- `POST /api/sessions/{session_id}/browser-events`
- `GET /api/sessions/{session_id}/stream`
- `POST /api/sessions/{session_id}/permissions`
- `POST /api/sessions/{session_id}/attachments`

## Next Slice Targets

Frontend slice:

- Promote `/chat` from redirect to primary Agent Hub chat surface.
- Reuse `@agent-hub/chat-ui`, but extend it for resume, fork, compact, continue, artifacts, permissions, and context/cost hints.
- Keep agent pages as specialized entry points, not the only chat surface.

Backend slice:

- Add durable app-event endpoints for browser events, artifacts, permission decisions, and compact context selection.
- Keep app events separate from model events.
- Add tests for event shape, client auth, permissions, and compaction.

Adapter slice:

- Define thin adapters for Codex, Claude Code, Jenny, and future clients.
- Normalize external streams into Agent Hub events.
- Keep artifact extraction in Agent Hub finalization.
