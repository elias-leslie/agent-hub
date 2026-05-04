# AGENT_AUDIT - agent-hub
_Sessions: 1 | Last run: 2026-05-04 | State: ISSUES_

## Architecture
- FastAPI backend in `backend/app`; SQLAlchemy/Alembic over PostgreSQL, Redis/Hatchet background work, async provider adapters for completions/streams.
- Next.js frontend in `frontend`; packages under `packages/` provide shared client/UI SDKs.
- Bundled Docker stack exposes frontend on `3003` and backend on `8003`; native run uses backend worker plus frontend dev server.
- Project targets Python 3.13+, Node 20+, pnpm 10.28.0.

## Project Tooling Notes
- Use `st` for dev workflow and repo gates. `st check` owns pytest, vitest, Biome, Ruff, TSC, and related checks.
- Current CLI has `st check cleanroom -- <command>`; top-level `st cleanroom` is not present in this run.
- `st pulse -P agent-hub --details`, `st sessions ownership -P agent-hub`, and `st sessions overlap -P agent-hub` are coordination preflight surfaces.
- `st ready` is project-auto only in this run; it does not accept `-P`.
- `st search` may return stale-index warnings; verify sensitive code facts with repo-local reads when it does.

## Active Work Context
- 2026-05-04 recurring hygiene session reviewed `st pulse`, session ownership, `st ready`, and active feedback.
- `st ready` showed P1 `task-17eba047` plus multiple P2 health/refactor items; none claimed yet.
- Reviewed `task-851af567`; fixed its backend raw-subprocess architecture slice and logged progress to the task.
- Active feedback list has 20 visible open items, mostly CLI/session/tooling friction.
- Preflight: no overlaps; one unrelated writer owned generated/package paths, so this session avoided those paths.
- Reported feedback `b68311de` for `st check --check` being blocked by an external CLI import crash.
- Verification: focused pytest 102 passed; changed-file gate passed ARCH/ruff/types/pytest. Full `st check --check` passed ARCH/ruff/types/tsc/vitest but failed repo-wide pytest and Biome on existing debt.

## Open Items
- [AH-AUDIT-003] [HIGH] [OPEN] Full gate still red on unrelated repo-wide debt - `st check --check` on 2026-05-04 failed pytest with 15 failures in memory reference injection/event storage/session events/seed model policy areas, and Biome with 689 errors/62 warnings in frontend files - changed-file gate for this session is clean; continue via `task-851af567`.

## Completed
- [AH-AUDIT-001] 2026-05-04 - Created project-local audit file with architecture, tooling, coordination, task, feedback, and verification context.
- [AH-AUDIT-002] 2026-05-04 - Consolidated runtime subprocess spawns behind `app.utils.safe_subprocess` to remove raw route/workflow/tool spawns from changed paths.

## Decisions
- Treat missing top-level `st cleanroom` as live CLI drift; use current `st check cleanroom -- ...` shape for cleanroom commands.
- Keep raw subprocess implementation centralized in `backend/app/utils/safe_subprocess.py`; route/workflow/tool code should call that wrapper.

## Human Follow-up
