# Persona Operator Contract

Thin canonical contract for `/persona` operator UX. Purpose: keep future work DRY, truthful, and inside current minimal tool surface.

## Product guardrails

- Primary surface is `/persona`. `/sessions` and `/persona/settings` support it; they do not replace it.
- Tool contract stays `read`, `write`, `edit`, `bash`. No plugin, marketplace, or tool-surface expansion.
- Persona naming stays dynamic. UI may show configured display name or neutral `persona` / `operator` copy. Never hardcode a specific persona name.
- Hermes is reference for interaction quality, not architecture parity.

## Source of truth

- Active or recent session truth: `fetchSessions` / `fetchSession`.
- Parent-child linkage truth: `session.parent_session_id`.
- Live run summary truth: `session.live_activity`.
- Stage execution truth: `/api/orchestration/workflow` response plus child sessions created by completion pipeline.
- Prompt-budget truth: existing preview/runtime prompt data. If live runtime lacks a metric, show preview-derived data as preview, not fact.
- Browser verification truth: `sf-browser` against host-IP lane URLs.

## Workflow semantics

- Workflow composer is orchestration over existing `clarify -> plan -> execute -> review -> qa` stages.
- A workflow run from a persona root thread must pass `parent_session_id` for every spawned stage request.
- Stage subset runs are valid. They create or update only requested stages.
- Later-stage outputs are advisory if an earlier stage is rerun. UI may keep them visible, but they must read as stale unless regenerated.
- `Approve` is UX-only until backend exposes a separate approval primitive. Current canonical continuation is rerun or run next explicit stage.

## Redirect and fork semantics

- `Redirect current work` means: send new instruction against selected session context. It does not mutate prior messages or erase prior outputs.
- `Stop` means cancel current live execution if backend still marks it active.
- `Fork lane` means create a new child session from current thread intent, not rewrite existing lane history.
- If backend lacks a dedicated redirect/fork API, UI uses explicit instruction text over current session primitives and must not pretend stronger guarantees than backend provides.

## Lane semantics

- Lane inbox shows child sessions for:
  - active persona root sessions
  - selected completed persona root session, when it still has active child work
- Lane count in HUD is based on runtime child-session truth, not only feed decorations.
- Inbox may merge runtime child sessions with `child_run` feed entries. Runtime status wins over stale feed status.
- `Resume` selects that session.
- `Redirect`, `Promote`, and `Handoff` are operator intents expressed through current session/message primitives unless a dedicated backend primitive exists.
- `Close` should not exist until backend truth can distinguish closed vs merely completed lanes.

## Blockers and budget

- Hard blocker precedence:
  1. explicit runtime/session error
  2. execution permission denied
  3. missing core capability
  4. advisory warnings
- Prompt budget should show authoritative token totals when available.
- If budget source is preview-only, label should remain explanatory rather than pretending live exactness.

## Automation semantics

- Automation controls reuse existing scheduler primitives.
- Manual trigger must surface immediate operator feedback plus report-back in persona-visible surfaces when produced.
- Report-back belongs in persona thread/timeline first. Secondary surfaces may summarize it.

## Verification minimum

- Raw session proof: child workflow session row carries correct `parent_session_id`.
- Operator proof: `/persona` HUD lane count and Lanes inbox reflect that child session.
- Redirect/interrupt proof: visible stop/redirect controls act on truthful session state.
- Dynamic naming proof: new surfaces render configured persona name or neutral labels; no hardcoded persona literal added by new work.
- Quality proof: `dt --check --changed-only` at minimum during iteration; full `dt --check` before closeout.

## References

- `~/references/hermes-agent`
- `~/references/pi-mono`
- `~/.claude/skills/frontend-design/SKILL.md`
