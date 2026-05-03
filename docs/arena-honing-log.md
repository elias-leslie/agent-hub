# Arena Honing Log

## 2026-03-20

### Objective
- Fold the old analytics surface into a broader `Arena` evaluation surface.
- Remove live hardcoded persona-display naming from runtime/UI/benchmark tooling.
- Make shared persona reads resolve from the persona identity source of truth.
- Keep exported defaults generic for fresh installs even while this system keeps a custom live persona name.

### Completed
- Added shared Arena UI for agent and persona routes:
  - `/persona/arena`
  - `/agents/[slug]/arena`
- Reworked the legacy analytics route into an Arena compatibility surface with the runtime view preselected.
- Removed direct analytics links from persona and agent editor headers and replaced them with Arena entry points.
- Added frontend persona display-name helpers and removed hardcoded runtime copy from the persona workspace/settings surfaces.
- Fixed shared backend persona-name resolution:
  - session display names now prefer `persona.name`
  - shared `/api/agents/persona` reads now resolve the live persona display name instead of stale cached `agents.name`
  - persona updates mirror the display name back to the backing agent row and invalidate the agent cache
- Renamed the benchmark/honing package out of `jenny_*` into `persona_*`:
  - `run_persona_model_benchmark.py`
  - `run_persona_honing_loop.py`
  - `persona_benchmark_*`
  - `persona_honing/*`
- Cleaned benchmark/honing prompt text so the live script package no longer hardcodes `Jenny`.
- Added `persona_display.py` to resolve the live persona name for benchmark prompts.
- Cleaned live DB prompt-store wording via `st prompt update`.
- Cleaned agent descriptions via `st agents update`.
- Normalized `export_seeds.py` so the checked-in seed export writes `Persona` for the persona agent name even if the live system uses a custom display name.
- Added suite and case summaries to the benchmark dashboard payload so Arena can surface suite health and brittle cases directly.
- Added a dedicated `Suites` tab in Arena with:
  - suite board
  - case watchlist
  - clearer high-level field status chips
- Added stable family-based suite IDs for related benchmark batteries, so Arena history stops fragmenting into opaque hash-only buckets for common case groups.
- Removed the dead legacy `AnalyticsHeader` component after the analytics route became an Arena compatibility surface.
- Cleared remaining `Jenny` references from active docs and test code; remaining hits are limited to historical git metadata or intentionally excluded artifacts.
- Hardened preview-panel accessibility with explicit control IDs and `aria-label`s after the broader frontend sweep exposed a label-resolution gap.
- Fixed the benchmark JSON parser so leading `[[P:...]]` narration tags no longer create false `invalid_json` failures in tool-using suites.
- Sanitized historical `jenny-*` suite labels on the Arena UI so old persisted benchmark identifiers display generically as `persona-*` without mutating stored history.
- Captured useful reference guidance from `autoresearch`, `openclaw`, and `aperant`:
  - immutable eval specs and scorer versions
  - shallow orchestrator trees with narrow specialist contracts
  - low-density topline scoreboards with drill-down on demand
  - avoid recursive fan-out and mutable eval harnesses

### Verification
- `dt pytest backend/tests/services/test_agent_service.py backend/tests/api/test_persona.py backend/tests/services/test_session_responses.py backend/tests/api/test_heartbeat.py backend/tests/workflows/test_instruction_review.py`
- `dt pytest backend/tests/scripts/test_export_seeds.py backend/tests/scripts/test_persona_model_benchmark.py backend/tests/scripts/test_persona_honing_loop.py`
- `dt pytest backend/tests/scripts/test_persona_model_benchmark.py backend/tests/scripts/test_persona_honing_loop.py backend/tests/api/test_agents_api.py backend/tests/services/test_agent_benchmark_service.py`
- `npm test -- src/__tests__/agent-analytics-page.test.tsx src/__tests__/persona-analytics-page.test.tsx src/__tests__/agent-arena-page.test.tsx src/__tests__/persona-arena-page.test.tsx src/__tests__/persona-page.test.tsx src/__tests__/persona-settings-tabs.test.tsx src/__tests__/agent-editor-shell.test.tsx`
- `dt -q -d`
- `bash ~/summitflow/scripts/rebuild.sh agent-hub`

### Browser Notes
- `st browser` could not reach `localhost:3003` directly from the browser session and returned `ERR_CONNECTION_REFUSED`.
- Using the host LAN IP worked:
  - `http://192.168.8.244:3003/persona/arena`
  - `http://192.168.8.244:3003/agents/persona/arena`
- Verified:
  - overview tab
  - suites tab
  - runtime tab
  - experiments tab
  - shared route resolves the live persona display name without frontend hardcode
  - historical `jenny-*` suite labels render as generic `persona-*` labels in Arena

### Remaining Name-Specific References
- Historical Alembic migrations
- Git metadata (`.git/`)
- Gitignored benchmark artifacts under `backend/.tmp/`

### Next Loop
- Replace ad hoc benchmark smoke tests with Arena-driven benchmark suites as the primary operator flow.
- Add run drill-down and attribution inside Arena.
- Expand the live battery from governance-only cases into task-authoring, delegation, and execution-sandbox cases.
- Use the new family suite IDs to establish stable baseline batteries before running broader honing loops.
