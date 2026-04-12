# Memory Routing

Memory injection must stay role-fit. Routing order:

1. Agent prompt sets role behavior.
2. Agent `memory_config` selects surface profile and coarse include/exclude gates.
3. Memory record `context_kind`, `applicability`, `trigger_task_types`, and `trigger_phases` decide eligibility.
4. Agent `exclude_memory_uuids` provides last-mile suppression for one-off bad fits.

## Consumer Profiles

Profiles change policy budget and rendering style. Current role-fit profiles:

- `agent_general`: lightweight general assistants
- `agent_visual`: design, image, and site-check roles
- `agent_coding`: coder, debugger, explorer, reviewer, tester class roles
- `agent_operator`: planning, supervision, triage, operational control
- `agent_promptops`: persona, governance, memory, prompt-maintenance roles

Startup-only profiles remain separate:

- `agent_preview`
- `agent_runtime`
- `claude_session_start`
- `codex_startup`

Use `runtime_consumer_profile` and `preview_consumer_profile` for explicit surface control. Use shared `consumer_profile` only as fallback when both surfaces should inherit same role.

## Memory Authoring Rules

- Put universal must-follow rules in mandate/guardrail policy memories.
- Put environment facts, tool quirks, service maps, and situational workflows in references or capabilities.
- Use `applicability.consumer_profiles` and `applicability.agent_slugs` for explicit targeting.
- Use `trigger_task_types` and `trigger_phases` for work-shape targeting.
- Do not use `audience_tags` to narrow mandates or guardrails.
- Use `exclude_consumer_profiles` or `exclude_agent_slugs` when one memory must stay out of a specific role.

## Agent Tuning Rules

- Disable mandate/guardrail/reference channels only when prompt or role already covers them.
- Keep project index and tool capabilities only for agents that benefit from repo/tool discovery.
- Use `exclude_memory_uuids` for surgical suppression when a single memory stays noisy after proper targeting.
- Prefer fixing the memory record over accumulating many per-agent exclusions.

## Inspection

- Use agent preview for effective context shape.
- Use session events to verify `refs:selected`, `index`, and citation rates after changes.
