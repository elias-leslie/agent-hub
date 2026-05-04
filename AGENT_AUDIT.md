# AGENT_AUDIT - agent-hub
_Sessions: 3 | Last run: 2026-05-04 | State: HEALTHY_

## Architecture
- FastAPI backend in `backend/app`; SQLAlchemy/Alembic over PostgreSQL, Redis/Hatchet background work, async provider adapters for completions/streams.
- Next.js frontend in `frontend`; packages under `packages/` provide shared client/UI SDKs.
- Bundled Docker stack exposes frontend on `3003` and backend on `8003`; native run uses backend worker plus frontend dev server.
- Project targets Python 3.13+, Node 20+, pnpm 10.28.0.
- Persona operator runtime tool surface is owned by `backend/app/services/tools/persona_tool_surface.py`; shared broad tool registries are not persona hot-load authority.

## Project Tooling Notes
- Use `st` for dev workflow and repo gates. `st check` owns pytest, vitest, Biome, Ruff, TSC, and related checks.
- Current CLI has `st check cleanroom -- <command>`; top-level `st cleanroom` is not present in this run.
- `st pulse -P agent-hub --details`, `st sessions ownership -P agent-hub`, and `st sessions overlap -P agent-hub` are coordination preflight surfaces.
- `st ready` is project-auto only in this run; it does not accept `-P`.
- `st search` may return stale-index warnings; verify sensitive code facts with repo-local reads when it does.
- Agent seed export is DB-sourced: update live agents with `st agents update`, then regenerate `backend/scripts/seed_agents_data/seed_data.json` via `backend/scripts/export_seeds.py`; do not hand-edit the generated JSON.

## Active Work Context
- 2026-05-04 follow-up claimed `task-851af567` slice `1.1` to clear remaining full-gate debt.
- Current session resolved stale memory-policy test expectations, event/session test mocks, Grok/xAI seed defaults in live Agent Hub config plus generated seed export, and frontend Biome debt.
- Verification: focused `st check pytest` 70 passed; `st check --quick --changed-only` passed ARCH/ruff/types/pytest/Biome/TSC; full `st check --check` passed ARCH/ruff/types/pytest 3368 passed/37 skipped, Biome, TSC, and Vitest 206 passed.
- Closeout: `st done task-851af567` committed task work, merged to `main`, removed checkpoint, and `st cleanup checkpoints --auto` pruned orphan task refs; final agent-hub pulse is clean with no unpublished work.

## Open Items
- None.

## Completed
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
