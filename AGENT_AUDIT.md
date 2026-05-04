# AGENT_AUDIT - agent-hub
_Sessions: 4 | Last run: 2026-05-04 | State: ISSUES_

## Architecture
- FastAPI backend in `backend/app`; SQLAlchemy/Alembic over PostgreSQL, Redis/Hatchet background work, async provider adapters for completions/streams.
- Next.js frontend in `frontend`; packages under `packages/` provide shared client/UI SDKs.
- Bundled Docker stack exposes frontend on `3003` and backend on `8003`; native run uses backend worker plus frontend dev server.
- Project targets Python 3.13+, Node 20+, pnpm 10.28.0.
- Persona API schemas are split by domain under `backend/app/api/persona/schema_*.py`; `schemas.py` remains the stable re-export surface.
- Persona operator runtime tool surface is owned by `backend/app/services/tools/persona_tool_surface.py`; shared broad tool registries are not persona hot-load authority.

## Project Tooling Notes
- Use `st` for dev workflow and repo gates. `st check` owns pytest, vitest, Biome, Ruff, TSC, and related checks.
- Current CLI has `st check cleanroom -- <command>`; top-level `st cleanroom` is not present in this run.
- `st pulse -P agent-hub --details`, `st sessions ownership -P agent-hub`, and `st sessions overlap -P agent-hub` are coordination preflight surfaces.
- `st ready` is project-auto only in this run; it does not accept `-P`.
- `st search` may return stale-index warnings; verify sensitive code facts with repo-local reads when it does.
- Agent seed export is DB-sourced: update live agents with `st agents update`, then regenerate `backend/scripts/seed_agents_data/seed_data.json` via `backend/scripts/export_seeds.py`; do not hand-edit the generated JSON.

## Active Work Context
- 2026-05-04 recurring hygiene reviewed `st pulse -P agent-hub --details`, `st sessions ownership/overlap -P agent-hub`, `st ready --limit 50`, `st feedback list --limit 50`, `st feedback summary`, audit open/completed items, VCS doctor, TODO/FIXME search, and targeted code/config scans.
- Parallelism used: two read-only explorer sidecars swept task/feedback queue and code/config/dependency debt. Findings integrated: stale test bugs, schema refactor, raw subprocess root resolver, tracked `backend/--output`, frontend lint suppressions, and remaining open clusters.
- Completed stale task cleanup for `task-235285e8` and `task-53b8efe2` after focused `st check pytest -- backend/tests/scripts/test_seed_agent_model_policy.py backend/tests/services/memory/test_reference_injection.py` passed 25 tests.
- Claimed and completed `task-3144db3f`; first `st done` push hit remote 500, retry succeeded, merged to `main`, deleted task branch, and removed checkpoint.
- VCS doctor reports cross-repo blockers outside agent-hub (`portfolio-ai`, `.codex`) but agent-hub pulse is clean before current-session edits; use agent-hub-local pulse/status for this closeout.
- `task-04380626` memory-yield audit found project reference memories `05cc0918` and `b23f83b0` had zero helpful/cited counts and duplicate coverage; deleted both. Narrowed `f0eb55a5` to Cloudflare/provider/model coding contexts. Verification: `st memory list -s project --scope-id agent-hub -t reference -l 100`, `st memory status`, and persona preview health signal improved `untargeted_refs` from 41 to 40.
- Reported new control-plane feedback `c48903d1` after `st context task-04380626` hit an import error in `cli.commands.tasks_context`.

## Open Items
- [AH-AUDIT-008] [MEDIUM] [OPEN] Feedback/prompt governance work remains - feedback `a8e0e474` and open feedback backlog need triage authority/queue shaping - impact: visible feedback remains too easy to accumulate without disposition.
- [AH-AUDIT-009] [MEDIUM] [OPEN] Maintainability backlog remains after schema/CRUD slices - ready refactors `task-354906ba`, `task-7984080d`, `task-69c7fa38`, `task-d8b9a77f`, `task-d5e78dde`; failed refactors need disposition - impact: large modules and failed cleanup attempts.
## Completed
- [AH-AUDIT-023] 2026-05-04 - Completed project memory-yield audit for `task-04380626`: removed duplicate zero-citation refs `05cc0918`/`b23f83b0`, narrowed `f0eb55a5`, and verified memory status plus persona preview signal.
- [AH-AUDIT-011] 2026-05-04 - Removed unused push workspace package, stale Docker tarball, lock importer, workflow pack step, and stale design-doc package reference; changed gate passed.
- [AH-AUDIT-018] 2026-05-04 - Closed stale readiness-sync task `task-9148c25d`; named repro task is completed/archived, plan creation already defaults missing subtask steps, and focused tool tests passed.
- [AH-AUDIT-019] 2026-05-04 - Closed stale cleanup-truth task `task-1e259848` and feedback `fd368ff4`; current cleanup is clean and exact reconciled-residue regression tests pass.
- [AH-AUDIT-020] 2026-05-04 - Closed stale shared-runtime shaping task `task-bdf784b7`; target runtime task was already ready with concrete subtasks.
- [AH-AUDIT-021] 2026-05-04 - Closed stale site-health/runtime cluster (`task-3ef41aa0`, `task-b4f9cf9c`, `task-8f81e9b7`, `task-78791f3c`, `task-36ef48ed`, `task-3dea84a5`, `task-55fe0ce2`) after live service, browser, and port checks passed on current host.
- [AH-AUDIT-022] 2026-05-04 - Split memory revision-history behavior into `_repo_revisions.py`; `_repo_crud.py` is 261 lines with 6 direct methods, and memory service tests passed.
- [AH-AUDIT-012] 2026-05-04 - Verified stale test-failure tasks `task-235285e8` and `task-53b8efe2` are fixed in current tree and closed them.
- [AH-AUDIT-013] 2026-05-04 - Split persona API schemas into focused domain modules while preserving `app.api.persona.schemas` imports; focused persona tests, ruff, types, frontend, and changed gates passed.
- [AH-AUDIT-014] 2026-05-04 - Replaced request-reachable raw `subprocess.run` in project root resolution with shared `safe_subprocess.run_process`; core tests passed.
- [AH-AUDIT-015] 2026-05-04 - Removed tracked accidental binary artifact `backend/--output`.
- [AH-AUDIT-016] 2026-05-04 - Removed three frontend lint suppressions in toast, session dropdown, and analytics tooltip; frontend gate passed.
- [AH-AUDIT-017] 2026-05-04 - Purged obsolete review-bot heartbeat prompt references from historical Alembic prompt migrations and closed related queue/feedback as stale.
- [AH-AUDIT-001] 2026-05-04 - Created project-local audit file with architecture, tooling, coordination, task, feedback, and verification context.
- [AH-AUDIT-002] 2026-05-04 - Consolidated runtime subprocess spawns behind `app.utils.safe_subprocess` to remove raw route/workflow/tool spawns from changed paths.
- [AH-AUDIT-004] 2026-05-04 - Collapsed persona operator tool surface to tiered core tools with code/doc source of truth and regression tests.
- [AH-AUDIT-003] 2026-05-04 - Cleared repo-wide full-gate debt: backend pytest regressions, generated seed model policy, and frontend Biome diagnostics now pass full `st check --check`.
- [AH-AUDIT-005] 2026-05-04 - Completed `task-851af567` verification scope with focused backend pytest, changed-file gate, and full repo gate all green.

## Decisions
- Treat missing top-level `st cleanroom` as live CLI drift; use current `st check cleanroom -- ...` shape for cleanroom commands.
- Keep raw subprocess implementation centralized in `backend/app/utils/safe_subprocess.py`; route/workflow/tool code should call that wrapper.
- No persona direct-tool exceptions are kept in the operator surface. Shared backend/non-persona registries may stay broad, but persona provisioning filters before deferred catalog exposure.
- Grok/xAI is not a default seed fallback for active text agents; keep mixed Codex plus non-Codex fallbacks with Claude/Haiku where needed.

## Human Follow-up
- None.
