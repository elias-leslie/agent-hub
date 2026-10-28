# Agent Hub Python Client

Async Python SDK for the Agent Hub API.

## Installation

```bash
pip install -e packages/agent-hub-client
```

## Quick Start

```python
from agent_hub import AsyncAgentHubClient

async with AsyncAgentHubClient(base_url="http://localhost:8003") as client:
    response = await client.complete(
        agent_slug="chat",
        project_id="agent-hub",
        messages=[{"role": "user", "content": "Hello!"}]
    )
    print(response.content)
```

## Features

- Sync and async completions
- SSE streaming via `stream_sse()` on both clients; the `done` chunk carries
  `fallback_used`, `agent_used`, `model_used`, cost and token counts
- Stateful conversations via `session(...)`
- Session management
- Full type hints
- Automatic error handling

### Canonical application integration (0.6.0)

This SDK is the only supported way to call Agent Hub from Python. Use it for
completions, agent metadata (`get_agent`, `list_agents`), context previews
(`preview_agent`), the model catalog (`list_models`), stored prompts
(`get_prompt`), service health (`health`), live project ownership
(`get_project_ownership`),
sessions (`get_session`, `list_sessions` with agent, parent, external-ID and
type filters), session events
(`list_session_events`, `append_session_event`) and automation-owner callbacks
(`list_automation_profiles`, `complete_automation_run`, `accept_automation_run`,
which take the owner's `internal_secret`). Never call private members such as
`_get_client` or `_inject_tracking_headers`; ask for a public method instead. Construct it from the application's configured
Agent Hub URL and registered client ID, with a stable `request_source`.
Keep provider credentials, model assignments, fallbacks and shared prompts in
Agent Hub. Applications own their domain validation, not alternative transports.

Pass `agent_slug` and `project_id` on completions. Omit `model` for normal agent
routing; a catalog `model` override is supported for explicit diagnostics and
is never silently ignored. Conflicting model mentions are rejected. Use
`disable_agent_fallbacks=True` when the selected provider is a requirement.
The response preserves actual model and fallback metadata; terminal provider
errors raise even if an older server incorrectly returns HTTP 200.

`system_prompt` supplements canonical context. `response_format` supplies the
JSON contract and validates the answer. Neither replaces application validation
before changing records. Provider quotas and failures must not be represented
as empty successful answers.

Build the wheel once from `packages/agent-hub-client`, then vendor that identical
versioned wheel in consumers and refresh their `uv.lock`. Never edit installed
SDK files or maintain copied SDK implementations. Existing sync and async clients
use the same response handler and identity configuration.

0.5.0 removed request fields the server never accepted (`purpose`,
`routing_config`, `resume_session_id`); `skip_cache` is sent as the
`X-Skip-Cache` header the server honours. CLI tools pass `source_client`
(for example `"st-cli"`) so Agent Hub classifies their traffic as CLI.

0.6.0 added `list_agents(is_coding_agent=...)`, the `list_sessions` filters
`agent_slug`, `parent_session_id`, `external_id` and `session_type`, and
`get_project_ownership`. Session responses now
carry routing, workspace and `live_activity` fields and keep any field the
server adds rather than dropping it.

0.7.0 deprecates `workflow()`: Agent Hub no longer serves
`/api/orchestration/workflow`, so the call emits a `DeprecationWarning` and the
method will be removed in 0.8.0. Compose `complete()` calls with an explicit
`agent_slug` instead.

### Model selection advice

`await client.select_model("coding", mode="shadow", assigned_model="codex/gpt-6.1-sol")`
returns model and effort advice for a generic task type, its source and date,
current route preflight, catalog freshness, and a comparison to the assigned
model. Discover task types with `await client.model_selection_policy()`. The initial
policy includes `general`, `coding`, `reasoning`, `visual_reasoning`, and
`writing`; the Agent Hub configuration may add others without a code change.
Set `AGENT_HUB_MODEL_SELECTION_POLICY_PATH` to an Agent Hub-owned JSON policy
file to manage it independently; the service reloads it for each request. The
selector rejects task contents. Supply
both `override_model` and `override_effort` for an explicit choice; capability
and availability checks still apply. Policies contain ordered candidates; the
response explains each skipped route. An override is a pin and is never silently
replaced. The response is advice: it does not call
a model or alter an agent's assigned chain. `mode="automatic"` returns
`apply=true` only for a current task-specific benchmark qualification of the
exact task, model and effort, a current local route qualification for that same
tuple, and a passing preflight. No route is currently qualified.
An opting-in caller can apply a qualified decision through its existing model
and effort override; it must check `apply` for every decision and retain its
assigned route otherwise. Route preflight checks catalog status, credentials and
provider cooldown, not entitlement or actual task success. Provider guidance
and inherited catalog scores are not benchmark evidence. Cost is not ranked:
subscription quota and metered API prices are not directly comparable.

Policy JSON contains a `version` and a `policies` object keyed by task type.
Each policy has ordered `candidates`, each with `model`, `effort`, `rationale`,
`source`, and `source_checked_at`; optional `requires_tools` and
`requires_vision` apply to all its candidates. A candidate can carry a
`qualification` object with `benchmark` and `local_route` evidence. Each
must identify `kind` (`task_benchmark` or `local_route_qualification`),
`source`, `assessed_at`, `valid_until`, `task_type`, `model`, and `effort`.
The dates are ISO dates. A qualification is scoped to that exact tuple and
must be current. Local route evidence also supplies `effective_effort`, which
must match the Agent Hub adapter mapping. The response distinguishes requested
and effective effort when known; max and ultra are unsupported by this selection
and completion contract. Configure policy changes atomically so readers never see a
partial file. `apply` is an advisory decision for an opting-in caller; Agent
Hub does not change assigned model chains or run the selection automatically.
