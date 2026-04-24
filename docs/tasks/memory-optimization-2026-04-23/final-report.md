# Agent Hub Memory Optimization Final

## Exports

- Active global export before: `201`
- Active global export after: `194`
- Active project export before (`agent-hub`): `30`
- Active project export after (`agent-hub`): `37`
- Net data move: `7` memories moved from global to project scope. No speculative deletes.

Artifacts:

- `global-active.json`
- `global-active-final.json`
- `project-agent-hub-active.json`
- `project-agent-hub-active-final.json`

## Live Surface Matrix

Post-rebuild live checks:

| Surface | Artifact | Loaded | Notes |
|---|---|---:|---|
| `claude_session_start` | `probe-claude-session-start-live.json` | 24 | `23` mandates, `1` guardrail, `0` refs |
| `codex_startup` | `probe-codex-startup-live.json` | 24 | `23` mandates, `1` guardrail, `0` refs |
| `coder` | `preview-coder-chat-live.json` | 20 | `policy_summary` |
| `planner` | `preview-planner-chat-live.json` | 26 | `policy_summary`; persona/Jenny spill removed |
| `supervisor` | `preview-supervisor-chat-live.json` | 26 | `policy_summary`; persona/Jenny spill removed |
| `memory-curator` | `preview-memory-curator-chat-live.json` | 26 | `policy_summary`; promptops rules remain, persona/Jenny removed |
| `prompt-builder` | `preview-prompt-builder-chat-live.json` | 26 | `policy_summary`; promptops rules remain, persona/Jenny removed |
| `persona heartbeat` | `preview-persona-heartbeat-live.json` | 29 | `policy_summary`; persona/Jenny rules still present |
| `persona wake` | `preview-persona-wake-live.json` | 26 | `policy_summary`; persona/Jenny rules still present |
| `chat` | `preview-chat-chat-live.json` | 0 | clean |
| `designer` | `preview-designer-chat-live.json` | 0 | clean |
| `site-checker` | `preview-site-checker-chat-live.json` | 0 | clean |

## Candidate Decisions

### Retargeted

| UUID | Summary | Decision | Reason |
|---|---|---|---|
| `7c847063` | Persona tool contract | retarget | Persona-only runtime rule. Restrict to `agent_slugs=['persona']`. |
| `65e20288` | Jenny max autonomy | retarget | Persona-only runtime rule. Restrict to `agent_slugs=['persona']`. |
| `0cefbf41` | Native Jenny Telegram | retarget | Runtime detail belongs to `agent-hub` persona only. Move global -> project, restrict to `persona`. |
| `86a18930` | No arbitrary Jenny task caps | retarget | Persona-only runtime rule. Move global -> project, restrict to `persona`. |
| `29888052` | Measure Jenny by Jenny work | retarget | Persona-only runtime rule. Move global -> project, restrict to `persona`. |
| `294b72c0` | Jenny coach monitors friction | retarget | Persona-only runtime rule. Move global -> project, restrict to `persona`. |
| `671c226d` | No Jenny canary gating | retarget | Persona-only runtime rule. Move global -> project, restrict to `persona`. |
| `8e9d0132` | Jenny autonomy boundary | retarget | Persona-only runtime rule. Move global -> project, restrict to `persona`. |
| `b4d9dd78` | Persona preview no-slug surface | retarget | Persona preview handling belongs to project promptops flow, not global. Move global -> project. |
| `c1252b83` | Preview matches runtime prompt | retarget | Promptops rule. Remove `agent_operator`; keep `agent_promptops`. |
| `bdee1bd4` | Prompt preview first | retarget | Promptops rule. Remove `agent_operator`; keep `agent_promptops`. |
| `919bbd8b` | st complete model override | retarget | Promptops rule. Remove `agent_operator`; keep `agent_promptops`. |

### Kept

| UUID | Summary | Decision | Reason |
|---|---|---|---|
| `15a165e7` | startup context from memory only | keep | Canonical startup architecture rule. Broad, but accurate and helpful. |
| `e5f41c36` | hook output: stderr vs additionalContext | keep | Current Claude startup behavior still matches repo + hook evidence. |
| `f05487e1` | sequential questions | keep | Current Claude skill/tooling still includes sequential question behavior. |
| `467f3273` | Agent Hub web wrapper | keep | Accurate project-specific web wrapper guidance. |
| `28ccdc0e` | Shell web-research first | keep | Accurate shell path guidance. |

### No Safe Change

- No safe demotions found. Tier issue was routing/applicability, not category label.
- No safe deletes found. Remaining low-yield startup references were still accurate and not live-loaded by current startup probes.
- No content rewrites needed. Scope/applicability fixes solved observed spill.

## Engine Findings

- `backend/app/services/memory/context_builder_tiers.py` mislabeled summarized policy loads as `startup_policy_summary` on non-startup surfaces.
- Fixed label to `policy_summary`.
- Added coverage in `backend/tests/services/memory/test_reference_injection.py`.
- Post-rebuild live previews now show `policy_summary` for `coder`, `planner`, `persona`, `promptops`, `supervisor`.
- Remaining startup heft is injector policy, not bad data: startup probes still intentionally load a flat L0 policy set (`23` mandates + `1` guardrail) and no references for the probe query.

## Verification

- `dt pytest -- backend/tests/services/memory/test_reference_injection.py backend/tests/api/test_agent_preview_helper.py`
- Result: `37 passed`
- `rebuild.sh agent-hub`
- Post-rebuild live previews/statuses captured in `*-live.json` artifacts.
- Leak check: `planner`/`supervisor` no longer load persona/Jenny or prompt-preview rules.
- Leak check: `memory-curator`/`prompt-builder` retain promptops rules, not persona/Jenny runtime rules.
- Clean check: `chat`, `designer`, `site-checker` still load zero memories.

## Confidence

- Final confidence: `97/100`
- Residual blockers: none under current verified surfaces.
