# Agent Hub value audit: execution plan (2026-10-10)

ST task: `task-2b4834a1c8e341ae`. The source is a usage-evidenced audit plus an adversarial review (skill:
`project-value-audit`). This file is the execution contract. The ST task
links here.

## Owner authority (granted 2026-10-10: "we'll do it all")

The owner approved every stage below, including:
- removing the persona page
- moving SummitFlow critical alerts from push to Telegram and retiring push
- deactivating the 127 test API keys
- retiring the SummitFlow fixture projects
- the Stage 4 table and column drops, **after** the archive is verified

Authority does NOT extend to:
- dropping any table not listed in Stage 4
- deleting `session_bindings`
- removing per-client `allowed_projects`
- folding runtime-context into the agent editor
- merging the memory backend
- removing Telegram delivery, the voice service, narration or image generation

Publication (`st vcs publish`) is separate and not requested.

## Hard rules for every agent

- Use the ST lifecycle: `st claim`, `st pulse --gate`, `st check --quick --changed-only`, `st commit -m ... --paths <owned files>`, `st done`. Never run raw pytest/vitest/tsc/biome/ruff, raw builds or `systemctl`.
- **Executors never run `st abandon` or `st rollback`.** Both restore the whole checkout and destroy other agents' work. Executors also never run `st service rebuild` and never edit integrator-owned files.
- Every writing agent claims its own subtask (`st claim <id> --task <parent>`). An unclaimed writer blocks `st pulse --gate` for everyone. Lease owned globs with `st lease`.
- `seed_data.json` is generated: export it from the live DB with `backend/scripts/export_seeds.py`. The seed script stays insert-only.
- DDL goes only through alembic migrations, in a single linear chain written by the integrator. The current head is `d1e2f3a4b5c6`. `st service rebuild agent-hub --detach` runs the migrations, so **a rebuild is the irreversible step for drops.**
- Never print secrets, key hashes or `.env` values.
- Agent Hub policy still applies: keep explicitly selected references separate from passive reference-index entries in injection events and analytics, and preserve both UUID sets and counts. Async paths use the managed `AsyncSession`. Don't hardcode token caps.
- Full `st check` (not changed-only) at every integration gate. Removals leave dangling imports in files nobody touched.

## Agent topology

- **Orchestrator/integrator (the main session):** creates and claims the parent task, and spawns the executors in parallel per stage, each with its own disjoint file set. It is the **only** editor of:
  - `backend/alembic/versions/*`, `backend/app/api/__init__.py`, `backend/app/models/__init__.py`, `backend/app/worker_runtime.py`
  - `backend/app/services/tools/_executor_registry.py`, `direct_executor_core.py`
  - `backend/app/services/automation_dispatch.py` (except subtask 1.4), `workflow_schedule_registry.py`
  - `frontend/src/components/layout/sidebar-nav.tsx`, `frontend/src/lib/api.ts`, `project.identity.json`
  - `scripts/seed_agents_data/seed_data.json`
  - `packages/agent-hub-client` and `packages/st-cli` releases, plus re-vendoring into consumers

  Executors return a short "integrator handoff" list of the edits they need in those files.
- **Verifier subagent per gate:** a fresh context checks the acceptance criteria against live evidence and reports pass/fail. Tests and live evidence are reported separately.
- Load the `orchestrate` skill for coordination.

## Key facts and evidence (do not re-derive)

- `request_logs` retains about 14 days. Requests carrying `X-Agent-Hub-Internal` (the whole dashboard UI) skip logging (`middleware/access_control.py:72-85`). `/api/runtime-context/*`, `/ws/` and `/api/memory/capture/stream` are not logged either.
- `pg_stat` row counts are stale. Always use `count(*)`.
- `/api/complete` real failure rate is about 2.6%. The 13% figure was probe and sweep bursts on 2026-10-09.
- SummitFlow removed its Work Chats UI in `ad114b065`. The headerless triggered-references caller was already fixed in SummitFlow `907aaf3be`.
- The Claude Code hooks' source of truth is `/srv/workspaces/projects/claude-config/hooks/`. The files in `~/.claude/hooks` are symlinks to it. Codex is unaffected.
- SDK wheel consumers:
  - agent-hub-client 0.6.0: summitflow (`docker/workspace-packages`) and design-tools (`vendor`)
  - agent-hub-client 0.5.0: jobinator-4000, learn-o-tron, neri and vantage (`backend/vendor`), portfolio-ai (`docker/workspace-packages`)
  - st-cli `agent_hub_st` 0.1.0: design-tools, neri and summitflow

  Hardcoded API path constants live in `packages/st-cli/agent_hub_st/_api_paths.py` and `summitflow/backend/cli/commands/_api_paths.py`.
- Archive location: `/srv/workspaces/projects/agent-hub/backups/2026-10-cleanup/`. It is durable and gitignored. Never use `/srv/scratch` for it.

---

## Stage 0: baseline (integrator)

**0.1** Create, claim and gate.
- Run a full `st check` and record the result.
- Record the baseline counts:
  - `/api/dashboard/stats?days=7` JSON
  - hook 404/422 counts per day (`request_logs` where `request_source='hook'`)
  - heartbeat rows per day
  - automation runs rejected per day
  - ownership/live polls of fixture projects
- Tag the start commit as the rollback point R0.

**0.2** Archive the tables before anything else.
- Read-only `pg_dump -Fc` of these tables:
  - the `pulse_*` set: `pulse_items`, `pulse_briefs`, `pulse_source_observations`, `pulse_feedback_events`, `pulse_improvement_proposals`
  - `webhook_subscriptions`, `client_controls`, `push_subscriptions`, `persona_scheduled_jobs`, `action_requests`
  - `api_keys`, `clients`, `session_bindings`, `automation_definitions`, `automation_profiles`, `workflow_schedule_controls`
- Write a `MANIFEST.json` with exact row counts and sha256 for each table.
- Test-restore into a scratch database and compare the counts.
- Use the managed DB credentials only, and print no secrets.

## Stage 1: trust fixes (4 parallel executors)

**1.1 Claude Code hooks** (repo `claude-config`; separate checkout, its own commit)
- Files: `hooks/SessionStart.sh` (around lines 52-53) and `hooks/PostToolUse.sh` (around 203, 208, 215-216).
- Bug: jq `($x|select(length>0))` empties the whole object when `$x` is `""`. The result is an empty body and a 422, then 404s for that session until the Stop hook upserts. In 3 days that was 8,347 404s and 576 422s, and 13 sessions were never created.
- Fix: `(if $x == "" then null else $x end)`, or build the object and then `with_entries(select(.value != "" and .value != null))`.
- Acceptance:
  - A harmless jq repro shows a non-empty body for empty task/branch/command/tmux values.
  - After deploying (the symlinks pick it up), a fresh Claude Code session row exists from SessionStart.
  - No new hook 422s or 404s.

**1.2 Ingestion and logging correctness** (agent-hub backend)
- `backend/app/services/session_ingestion/_service_helpers.py` (around 135-138): the upsert must not overwrite `external_id`, `agent_slug` or `current_branch` with null or empty values. Only 59 of 1,483 claude_code sessions still have an `external_id`. Add a regression test.
- `backend/app/api/complete/streaming.py` (around 84-135): in the finalize step, call `log_token_usage`/`CostLog` the way the non-streaming path does (`handler_helpers.py:106`). Currently 0 of 192 chat sessions have cost rows. Add a regression test.
- `backend/app/middleware/access_control_handlers.py` (around 72, 111):
  - Pass `session_id` into `log_request`: set `request.state.session_id` in the complete and session handlers.
  - Stop writing successful heartbeat requests to `request_logs`: both `/api/session-ingestion/sessions/{id}/heartbeat` and `/api/sessions/{id}/heartbeat`. Keep non-2xx heartbeats.
  - Keep `GET /api/access-control/metrics` working. It is used by `st tools` metrics, whose numbers will shift; note that in the commit.
- `backend/app/middleware/access_control_auth.py` (around 19): write `clients.last_used_at` when `get_cached_client` misses its cache (that is, once per TTL). Delete the dead `ClientAuthService.identify()` writer, or route it through this path.
- Acceptance:
  - Tests pass.
  - After rebuild, a streaming chat writes a `cost_logs` row.
  - Heartbeat rows stop appearing.
  - `session_id` is populated on new `request_logs` rows.
  - Active clients show a current `last_used_at`.

**1.3 Dashboard truthfulness** (agent-hub)
- Files:
  - backend: `backend/app/api/dashboard_stats.py`, `backend/app/api/health_logic.py`, `backend/app/routing/availability.py` (or the provider-status surface)
  - frontend: `frontend/src/components/dashboard/*` (`KPISection.tsx`, `HealthTabContent.tsx`, `ChartsSection.tsx`), `useDashboardData.ts`
- Changes:
  - The request, latency and success KPIs count only model-call endpoints (`/api/complete` and the streaming complete path), not every HTTP row.
  - Fix the double scaling in `HealthTabContent.tsx:148,155`: `success_rate` is already 0-100. Also stop showing HTTP success as "memory success".
  - Use `!= null` checks so 0% renders as 0% (`KPISection.tsx:64,69,98-108`).
  - Make the Request Volume chart and the KPI use the same population.
  - Label cost as "metered spend (API-billed calls)".
  - Provider status includes recent failures from completion outcomes.
  - Remove the circuit-breaker stub, the Timeouts KPI, the Fallbacks KPI and the truncation panel.
  - Keep the selected-vs-passive memory-injection counts visible somewhere on the dashboard. This is required by policy.
- Acceptance:
  - Tests pass.
  - `/api/dashboard/stats` values match independent SQL.
  - A headless check of `/dashboard` shows no NaN, overflowing bars or 0% shown as "100%".

**1.4 Scheduler and SummitFlow noise** (agent-hub `services/automation_dispatch.py` and summitflow)
- Agent Hub `dispatch_due` (around line 233): skip profiles whose project policy is disabled. Advance `next_run_at` without inserting a run row. Leave manual `admit_run` unchanged, and keep the CANCEL_NEWEST overlap policy. Today the 3 jobinator profiles create about 439 rejected runs a month. Add a regression test.
- SummitFlow `backend/app/api/tasks/list_endpoints.py` (`_build_ready_all_overview_response`, around 227): exclude `testing_project_ids()` and retired projects before `fetch_live_project_inventory`, the same way `/projects` does.
- SummitFlow data: retire the fixture projects through managed SummitFlow commands, not raw SQL:
  - test1, test2, test3, test-project
  - delete-017b002c, WIP
  - the `*-fixture` projects
- Check that SummitFlow tests mock Agent Hub instead of calling the live `/api/projects/test-project/execution-permission`. Fix them if they don't.
- Commit in the SummitFlow repo with its own `st` lifecycle.
- Acceptance: tests pass, no new `project_disabled` runs, and no fixture polls in `request_logs`.

**Gate 1 (integrator):**
- Full `st check` in agent-hub (and in SummitFlow for 1.4).
- `st service rebuild agent-hub --detach`, then wait for health. Rebuild SummitFlow if 1.4 changed deployed code.
- A verifier subagent checks every acceptance above against live data.
- Commit and tag R1.

## Stage 2: delete confirmed-dead code (3 parallel executors, code only, no drops)

**2.1** Delete:
- `backend/app/services/container_manager.py`
- `backend/app/services/context_maintenance_worker.py` (keep `context_maintenance_actions` and its MCP/CLI paths)
- `backend/app/services/typesafe_jev.py` and `backend/app/api/typesafe_jev_schemas.py`
- `backend/app/services/context_screening.py` together with `backend/scripts/evaluate_context_review.py`

Also remove the `mode="jev"` branch in `context_review.py`. Keep the jev catalog entry and the typesafe credential provider.

**2.2** Remove webhooks: `api/webhooks.py`, `services/webhooks.py`, the webhook workflow, and the webhook docs in `events.py`. Hand to the integrator:
- `webhook_delivery_task` in `OPS_WORKFLOWS` in `worker_runtime.py`
- the `/api/webhooks` exempt entry in `middleware/access_control_paths.py`
- the `WebhookSubscription` model in `models/config.py`
- router registration

**2.3** Admin, embed and the client control plane:
- Delete the `/embed` page.
- Remove the kill switch, which writes `client_controls` but nothing reads it: the `admin.py` client-control endpoints around lines 46-140, and `frontend/src/lib/api/admin.ts` client functions. Keep `/schedules`, `/request-audit`, `/unknown-callers`, `/session-hotspots`, `/admin/telegram` and `/admin/db`.
- Make the Admin page reachable as an Access Control tab or a nav entry.
- Remove the unenforced client `rate_limit_rpm`/`rate_limit_tpm` from:
  - `access_control_schemas.py`, `access_control_clients.py`, `access_control_helpers.py`, `api_key_helpers.py`
  - the `access-control/clients/new` form and the list UI
- Do NOT touch the provider rate-limit cooldown (`agent_routing_completion.py:82-94`, `complete_orchestrator.py:99`).

**Gate 2:** integrator edits the registries, sidebar and barrel, runs a full `st check`, rebuilds, has a verifier sweep for dangling routes and imports, and tags R2.

## Stage 3: coupled removals (4 parallel executors; integrator owns migrations and SDK)

**3.1 Persona page**
- Delete `frontend/src/app/persona/**` and its tests, plus persona-only `lib/api/persona*` frontend clients that nothing else imports.
- Fix the redirect in `frontend/src/app/agents/[slug]/page.tsx:41`.
- **Keep:**
  - the backend persona API (used by `st persona`, `packages/st-cli/persona_api.py`)
  - the `persona` agent and context bridge (`runtime_prompt_stack.py:283`, used by portfolio-ai `_jenny_conversation_llm.py:58`)
  - `persona_identity`
  - `persona.voice_*` (TTS)
  - `components/chat`, because `use-models` is shared
- Guard `packages/chat-ui` `use-voice-preferences.ts` if it relies on removed endpoints.

**3.2 Persona heartbeat, scheduler and wake**
- First move the shared helpers (`_heartbeat_workstream`, `_heartbeat_data` and the like, used by `cleanup_summary.py`, `_executor_io_cleanup.py`, `api/helpers/agent_preview.py` and `automations.py`) into a neutral module.
- Then remove:
  - `workflows/_heartbeat_*`, `persona_scheduler`, `automation_persona.py`, `api/heartbeat.py`, `api/wake.py`
  - the persona `dispatch_wake` on autocode failure in `workflows/completion.py`
  - the heartbeat and wake preview modes
  - the `persona_job` branches in `automations.py` (around 369-636)
  - `review_improvement_signals` from persona tooling only if nothing else uses it. Keep the benchmarks and the improvement-signal data.
- The integrator writes a migration that removes the `automation_definitions` rows `agent-hub.persona_heartbeat`, `persona_job` and `persona_scheduler`, their profiles, the `workflow_schedule_controls` rows and the schedule registry entries.
- Adjust `send_jenny_telegram_status_report` (the `agent-hub-telegram-status-report` timer) so it no longer reads the heartbeat schedule. **Telegram delivery and both user timers keep working.**
- Update `/api/heartbeat` in st-cli and in summitflow `_api_paths.py`.

**3.3 Work Chats routes (keep bindings)**
- Move `apply_work_chat_metadata` and the binding upsert from `services/work_chats.py` into a session-binding module. They are used by `api/complete/request_setup.py:111`, `streaming_handlers.py:85`, `event_storage.py:156-239` and `routing/resolution.py:56`.
- Then delete `api/work_chats.py`, the rest of `services/work_chats.py`, `work_chat_verifier_outcomes.py` and the action-request model.
- **Keep the `session_bindings` table.** It is written by design-tools `st.design.asset.critique` (`design-tools/.../design.py:314`). Keep the `work_context`/`source_metadata` request fields, which the-aftertimes Godot client sends.
- Remove the disabled Telegram bot service, its code and its `project.identity.json` optional-worker entry. The binding Telegram columns can stay.

**3.4 Push to Telegram, orchestration, API keys**
- In SummitFlow, make `backend/app/services/notifications/delivery.py:37` send critical/error notifications through Agent Hub Telegram delivery (the existing endpoint `/api/notifications/telegram`) instead of `/api/push/send`, then remove the push export. Then remove in Agent Hub:
  - `push_*`, `api/push.py`, the push model
  - `send_push`/`SEND_PUSH_TOOL`, including from the persona allow-lists in `project_permission_service.py:112,128` and from `_executor_registry.py:265`
- Orchestration:
  - Delete `committee_roundtable_service.py`; nothing in the repo calls it. Keep Vantage's `propose_committee`.
  - Deprecate `workflow()` in agent-hub-client 0.7.0. Remove the `/api/orchestration/*` routes and `api/endpoints/*` that only they use, after the 0.7.0 release.
  - Remove `examples/orchestration_example.py`.
- API keys: deactivate all 127 rows. They are test leftovers (`test-project`, `default`, `rotate-test`, `test`, `project-a`), created in January 2026 and never used. Use a reversible data migration or a managed admin path. Keep the `require_api_key` mechanism.

**Gate 3 (integrator):**
- One linear migration for the Stage 3 data changes.
- Release agent-hub-client 0.7.0 and update st-cli paths. Re-vendor only into consumers that need it (summitflow, design-tools, plus any that call `workflow()` or the push and heartbeat paths). Run each consumer's `st check`.
- Export `seed_data.json`.
- Full `st check`, rebuild, then live checks:
  - Claude Code session start
  - `st persona` commands
  - a portfolio-ai-style `agent_slug=persona` completion
  - a design-tools binding write
  - Telegram status report and host-guardian alert dry run
  - SummitFlow critical notification reaching Telegram
- Tag R3.

## Stage 4: data drops (approved; archive verified first)

- The integrator writes one idempotent migration (`DROP ... IF EXISTS`; the downgrade recreates the schema, and data restores from the archive). It drops:
  - `pulse_items`, `pulse_briefs`, `pulse_source_observations`, `pulse_feedback_events`, `pulse_improvement_proposals` (no owning model; use raw `DROP TABLE IF EXISTS`)
  - `webhook_subscriptions`, `client_controls`, `push_subscriptions`, `persona_scheduled_jobs` (only after 3.2 removes all readers), `action_requests`
  - the `clients.rate_limit_rpm` and `clients.rate_limit_tpm` columns
- Before the rebuild, re-check that `MANIFEST.json` counts still match. If any table gained rows, stop and report.
- Rebuild (this is the irreversible point), then the verifier confirms health and the absence of errors referencing the dropped tables in logs. Tag R4.

## Stage 5: consolidation (after Stage 4)

**5.1 Instrumentation.** Add sampled logging of internal-header (UI) requests to `request_logs`, with a source like `agent-hub-dashboard-ui`, so future usage decisions can see UI traffic. Ship it now; the decisions it informs come later.

**5.2 Context maintenance.** Merge `context_maintenance*.py`, `context_review.py`, `context_governance.py`, `context_reviewer_identity.py` and the rest into **3–4** modules. Preserve:
- `context_governance.record` callers (`memory_rater.py:73`, `_review_agent_runner.py:76`)
- `runtime_context.py:683`
- `/api/runtime-context/manage/{inventory,save,maintenance}`
- `memory-scope/{preview,apply}` (st-cli contracts)

This is a behavior-preserving refactor; the roughly 172 existing tests must pass unchanged.

**5.3 Navigation.** Group Agents, Models, Prompts, Memory and Agent context under one "Agents" nav section. Keep the runtime-context preview at consumer-profile scope as its own page. Keep the memory Analytics tab.

**Gate 5:** full check, rebuild, verifier, `st done` on the parent with evidence.

## Deferred (not in scope; needs instrumentation evidence first)

- memory backend or API consolidation
- removing the memory Capture tab
- removing the `/chat` page
- removing `require_api_key`
- removing the `/api/wake` route if anything still needs it after 3.2
- freezing benchmarks

## Final report

Per stage, report:
- commits and rollback tags
- tests vs live evidence, kept separate
- anything skipped, with the reason
- lines removed
- cross-repo commits (claude-config, summitflow, design-tools and other consumers)
- open follow-ups

## Owner decisions during execution (2026-10-10)

- `persona_scheduled_jobs` readers: remove `/api/persona/improvement`, `/api/persona/improvement/schedule`, `/api/persona/automations*` and `scripts/persona_honing/*` scheduling with 3.2 (no traffic in 14 days, not used by `st persona`), then drop the table in Stage 4 as planned. Move `compute_next_run` only if a kept caller remains.
- SummitFlow alerts: 3.4 also fixes `storage/notifications.py:95-104` (delivery skipped without a running event loop) and sends critical/error notifications to the existing `/api/notifications/telegram` chat with a severity prefix.
- 2.3 narrowing: API-key rate limits (`api_key_helpers.py`, `api_key_auth.py`) are enforced and stay; only client-level `rate_limit_rpm`/`rate_limit_tpm` are removed.
- `seed_data.json` lives at `backend/scripts/seed_agents_data/seed_data.json`.
