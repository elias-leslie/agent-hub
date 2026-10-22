# Session roles and comparable accounting

A work role is an explicit declaration for one native Hub `Session.id`. The owning registry is
`backend/app/services/session_roles.json`. IDs are stable; display names may be customized.
An absent legacy declaration is **Unknown**, distinct from the declared **Other** role.
No role comes from a prompt, title, mutable widget role, or parent session. Forking does not
copy the parent's declaration.

A launcher should add this minimal payload to its existing `POST /api/session-ingestion/sessions/upsert`
request (or `POST /api/sessions` request):

```json
{
  "session_id": "the-existing-native-session-id",
  "project_id": "the-existing-project-id",
  "provider": "the-existing-provider",
  "model": "the-existing-model",
  "work_role": {"id": "implementation", "source": "the-producer-and-explicit-declaration-source"}
}
```

`work_role.display_name` is optional. Producers that already write provider metadata may
instead send the same declaration as `provider_metadata.work_role`. An explicit initial
coordinator declaration uses `id: coordinator` and names that source; it is not inferred.
The server stamps `declared_at`. Session DTOs expose `{id,label,source,declared_at,display_name?}`.
The first declaration and its provenance persist. Repeating its ID is idempotent, even if
later display/source values differ. Omission or null on upsert/heartbeat preserves it.
A differing ID returns HTTP 409 (`error: session_work_role_immutable`); a different role
needs a new native session. Existing external identity and scope fields are preserved.
Native Codex and Pi sync use this same upsert/merge path, with session ingestion locks.
Launcher production is a separate integration change; no recurring command tagging is required.

## Query and DTO

`GET /api/admin/session-efficiency` returns the Activity snapshot, adding:

- `context_split`: estimated tool text added once, the headline measure.
- `duration_split`: secondary measured tool duration split.
- `by_project`, `by_work_role`, `by_harness`: complete group arrays, not limited by `limit`.
- `work_roles`, `harnesses`: canonical `{id,label}` filter options, including Unknown.

Group rows have `project_id`, `work_role_id`, or `harness_id`, plus `label`, `sessions`,
`context_split`, `duration_split`, `usage`, `cost`, and `coverage`. Shares use summed estimates or duration totals,
never the average of session percentages. Accounting without a matching Hub session
remains in the existing unmatched accounting fields; group usage/cost covers Hub-linked
sessions only. Existing source precedence is unchanged: cost logs, matched usage calls,
then deduplicated response events; alternative sources are never added for one session.

`context_split` reports `admin_tokens_estimate`, `other_tokens_estimate`,
`unknown_tokens_estimate`, `denominator_tokens_estimate`, `argument_tokens_estimate`,
`returned_tokens_estimate`, the three shares, and coverage (`tools_sampled`,
`tools_missing_output`, `tokenized_argument_calls`, `estimated_argument_calls`,
`events_truncated`). `input_token_encoding` and `output_characters_per_token` expose
configured estimation methods. Arguments use the reference tokenizer within the existing
per-call and per-session character budgets, with character estimates beyond either budget.
Output uses the configured character/token ratio on retained result length without loading
its text into the response. Wrapper suppression and call pairing match tool-time accounting.
Empty denominators have null shares. Other includes unknown, and unknown is shown explicitly.
Group estimates sum session estimates, never average percentages. Missing or truncated
output has unknown size. A non-null result length can come from the capped/redacted
`SessionEvent.content` summary fallback; retained-text call coverage is not complete-output
coverage. Summaries can undercount model-seen output. Counts cover retained text only, once per call; prose, system
instructions, images, protocol framing, repeated context reads and compaction are excluded.
This is neither resident context-window occupancy nor an allocation of provider usage/cost.
No resident-context measurement is available in the list or Activity contract. Native provider
usage stays separate; the Sessions row usage is cumulative while Activity usage is windowed.

`duration_split` fields are `admin_seconds`, `other_seconds`, `denominator_seconds`,
`admin_share`, `other_share`, `unknown_seconds`, `unknown_share`, `tools_sampled`,
`tools_missing_duration`, `duration_coverage`, and `events_truncated`.
The denominator is the union of recorded non-wait runtime intervals per session; concurrent
sessions add. Administration includes support. Other includes substantive plus unknown/mixed.
Missing duration has unknown size, not an invented zero. Known zero duration contributes
to call coverage but cannot establish a duration share. Empty denominators have null shares;
no sampled calls have null coverage. Coverage counts calls with reported duration and
placement, including known zero and explicit waits. Explicit wait-only occupancy is excluded
from the duration denominator. All shares are fractions in `[0,1]`.

`usage` retains existing inclusive input, output, cache-read/write, and cache-detail input
partitions. `cost` contains `recorded_calls`, `api_equiv_known_calls`, `cash_known_calls`,
`api_equiv_usd`, and `cash_usd`. Amounts are null without known values and otherwise sum only
known calls; use known-call counts to disclose partial pricing. Native transcript usage does
not establish cash spend. API-equivalent value is distinct from cash. `coverage` contains
`usage_sessions` and `missing_usage_sessions`. No token-purpose or waste allocation is implied.

Harness provenance uses `provider_metadata.external_identity.harness`, then
`provider_metadata.harness`, then registered native `request_source` markers or canonical
Pi ingestion type. The registry and accepted aliases live in `session_harnesses.json`.
Provider, model, title, and mutable role are not harness evidence; unproven legacy identity
(including Agent Hub, Claude Code, or Antigravity) remains Unknown.

Supply both `accounting_start` (inclusive ISO timestamp) and `accounting_end` (exclusive ISO
timestamp), with timezones. Last hour/day/week are ordinary 1/24/168-hour intervals.
Legacy `hours`/`until` remains supported on Activity when explicit dates are absent.
Both Activity and Sessions accept `project_id`, `work_role`, `harness`, `kind`, `status`,
`model` (requested model), `roots_only`, `exclude_benchmarks`, `q`, `since`, `agent_slug`,
`parent_session_id`, `session_type`, and `external_id`. Activity additionally keeps its
existing `provider` and `session_id` filters. Filters apply before source limits.
Activity retains its existing window-active session selection and event cap; `events_truncated`
and all missing/unknown fields remain explicit. A truncated sample can omit evidence, so
its shares are sample observations. Sessions can also show inactive historical matches.

`GET /api/sessions` adds `activity_accounting` (duration fields plus nested `context_split`) to every row, `accounting_window: {start,end}`,
and both registries to the response. Facets also return both registries. The first Sessions
request defaults to a trailing 24-hour accounting window. `next_cursor` pins that window
for every sort; later pages may omit dates, and changing them is rejected. Offset pagination
must resend the same explicit dates. `sort_by=admin_share|admin_tokens|admin_duration` and existing
`sort_direction=asc|desc` sort all filtered sessions before pagination. `admin_share` uses the displayed context share;
`admin_tokens` uses estimated admin tool tokens, and `admin_duration` retains tool time. Unavailable denominators
sort last in either direction, with stable session-ID ties. These sorts stream all retained
tool records in the interval without a source/session cap; per-session pairing, overlap union,
wrapper suppression, and interval boundaries match Activity. The existing row usage rollups
remain lifetime totals; comparison usage belongs to the explicit Activity interval.

## Verification and integration

Focused unit/API tests cover immutable roles, fork behavior, missing versus zero duration,
wait/overlap handling, weighted groups, explicit harness evidence, cost-source precedence,
and cursor windows. Isolated PostgreSQL tests exercise actual routes, shared filters and
ledger totals, pre-pagination sorting in both directions, pricing fields, and cap disclosure.
These are test-environment checks, not deployment evidence. Rendered and deployment evidence
belongs to the dated audit for the integrated revision.
