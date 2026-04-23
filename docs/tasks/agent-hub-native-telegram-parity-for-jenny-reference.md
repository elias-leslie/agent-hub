# Agent Hub native Telegram parity for Jenny reference

Authority order
- `docs/tasks/agent-hub-native-telegram-parity-for-jenny.plan.json`
- this reference doc
- canonical `agent-hub` code/tests
- donor/reference implementations in `/srv/workspaces/projects/agent-hub-telegram-bot-v1` and `/home/kasadis/references/hermes-agent`

Goal
- Make canonical `/srv/workspaces/projects/agent-hub` own Jenny's Telegram path natively.
- Upstream the working v1 bot/config/admin/systemd surfaces into canonical Agent Hub.
- Port Hermes-grade Telegram rendering behavior into an Agent Hub-owned stack without any runtime Hermes dependency.
- Keep Hermes and `agent-hub-telegram-bot-v1` as donor/reference implementations only until native parity is proven and cutover is safe.

Donor surfaces to inspect, not edit
- `/srv/workspaces/projects/agent-hub-telegram-bot-v1/backend/app/services/telegram_config_service.py`
- `/srv/workspaces/projects/agent-hub-telegram-bot-v1/backend/app/services/telegram_delivery.py`
- `/srv/workspaces/projects/agent-hub-telegram-bot-v1/backend/app/services/telegram_bot_service.py`
- `/srv/workspaces/projects/agent-hub-telegram-bot-v1/backend/app/api/admin_telegram.py`
- `/srv/workspaces/projects/agent-hub-telegram-bot-v1/backend/app/scripts/run_telegram_bot.py`
- `/srv/workspaces/projects/agent-hub-telegram-bot-v1/backend/app/scripts/send_jenny_telegram_status_report.py`
- `/srv/workspaces/projects/agent-hub-telegram-bot-v1/scripts/systemd/agent-hub-telegram-bot.service`
- `/srv/workspaces/projects/agent-hub-telegram-bot-v1/scripts/systemd/agent-hub-telegram-status-report.service`
- `/srv/workspaces/projects/agent-hub-telegram-bot-v1/scripts/systemd/agent-hub-telegram-status-report.timer`
- `/home/kasadis/references/hermes-agent/gateway/platforms/telegram.py`
- `/home/kasadis/references/hermes-agent/tests/gateway/test_telegram_format.py`
- `/home/kasadis/references/hermes-agent/tests/gateway/test_telegram_text_batching.py`

Native ownership rules
- The canonical runtime lives in `/srv/workspaces/projects/agent-hub`.
- Do not keep a plain-text-only Telegram stack in canonical Agent Hub once the shared renderer exists.
- Do not add a runtime import or subprocess dependency on Hermes.
- Do not edit anything under `~/references/`; copy or reimplement the needed behavior in canonical Agent Hub.
- Do not treat `agent-hub-telegram-bot-v1` as the final production location after this task; it is a staging donor only.

Config and bootstrap contract
- First-party client id: `agent-hub-telegram-bot`.
- Project id for DM chat completions: `agent-hub`.
- Agent slug for DM chat completions: `persona`.
- Request source for DM chat completions: `telegram`.
- External id format for DM chat sessions: `telegram:dm:<chat_id>`.
- Environment override keys:
  - `AGENT_HUB_TELEGRAM_BOT_TOKEN`
  - `AGENT_HUB_TELEGRAM_ALLOWED_CHAT_IDS`
  - `AGENT_HUB_TELEGRAM_REPORT_CHAT_ID`
- Stored credential namespace:
  - provider `_system_telegram_bot`
  - credential types `bot_token`, `allowed_chat_ids`, `report_chat_id`
- Precedence is fixed: env override > stored credential > unset.
- Empty allowlist must not block bot startup. The operator needs to be able to DM `/start` first to discover the chat id needed for bootstrap.

DM bot contract
- Unauthorized private chats reply exactly:
  - `This chat is not authorized yet. Chat ID: <chat_id>. Ask the operator to add it in Agent Hub.`
- Unsupported non-text content replies exactly:
  - `This bot supports text messages only in v1.`
- `/reset` replies exactly:
  - `Conversation reset. Your next text message will start a fresh Jenny conversation.`
- `/start` on an allowed chat must confirm Jenny is connected, echo the chat id, show whether reports are bound, and mention `/status` and `/reset`.
- `/status` on an allowed chat must show chat id, allowlist status, report binding status, runner status, and current session id or `none`.
- Session reuse rule is fixed: reuse the stored session id when present, otherwise fetch the latest session for `external_id=telegram:dm:<chat_id>`, and only force a new conversation after `/reset` clears the stored session and sets the one-shot force-new flag.
- DM completions must call `/api/complete` with `use_memory=true`, `enable_caching=false`, `skip_cache=true`, `execute_tools=true`, `enable_programmatic_tools=true`, and `max_turns > 1` so Jenny actually runs the tool loop instead of emitting pseudo-tool traces.
- DM replies must send through the shared Telegram delivery helper, not through a plain `reply_text(...)` shortcut.
- When a DM reply splits into multiple Telegram messages, only the first chunk replies to the inbound Telegram message. Later chunks continue unthreaded with a visible continuation suffix.

Renderer and delivery contract
- Canonical Agent Hub must expose one shared Telegram renderer/delivery stack used by both DM chat replies and scheduled/operator sends.
- Rendering requirements are fixed for this task:
  - protect fenced code blocks and inline code before escaping
  - convert normal markdown into Telegram MarkdownV2
  - wrap GFM pipe tables in fenced code blocks before markdown conversion so tables stay readable
  - preserve markdown links, headers, bold, italic, strikethrough, spoiler, and blockquote semantics when possible
  - on MarkdownV2 parse failure, retry once with stripped plain text rather than dropping the message
- Chunking requirements are fixed for this task:
  - Telegram chunking must use UTF-16-aware length accounting
  - each chunk must stay within Telegram's 4096-character limit after any continuation suffix is added
  - prefer paragraph/newline boundaries before hard splits
  - multi-part sends append a visible ` (n/N)` continuation suffix, and MarkdownV2 chunks must escape the suffix parentheses so Telegram accepts them
  - whitespace-only sends are skipped instead of causing Telegram empty-text errors
- Link preview policy is explicit and caller-owned:
  - DM replies use `disable_link_previews=false`
  - scheduled/operator/report sends use `disable_link_previews=true`
  - both paths still use the same shared renderer and chunk sender

Scheduler and automation contract
- The scheduler/data-model delivery enum for this task is `none | push | telegram`.
- `delivery=telegram` is only supported for `payload_type=agent_turn` in this task. Do not invent direct Telegram delivery for `push` or `self_honing` payload types here.
- The delivery target for scheduled/operator sends is the single configured `report_chat_id`.
- Both cron-driven scheduler execution and manual `POST /persona/automations/{job_id}/trigger` must use the same `_maybe_send_delivery_telegram(...)` helper after the agent turn completes.
- The task does not add per-job Telegram chat routing, group-chat routing, or topic routing.
- The dedicated operator report script/timer remains a separate one-shot bridge that asks Jenny for a grounded report and then sends it through the same shared Telegram delivery helper.

Systemd and rollout contract
- Canonical Agent Hub must gain repo-owned service/timer templates for:
  - `agent-hub-telegram-bot.service`
  - `agent-hub-telegram-status-report.service`
  - `agent-hub-telegram-status-report.timer`
- The report timer/service may coexist with the old sidecar during verification.
- Do not disable Hermes or the sidecar services until canonical Agent Hub passes tests and at least one native canary send/dry-run path is verified.

Out of scope for this task
- group chats
- forum topics
- media, voice notes, and photo handling
- webhooks
- callback queries and inline mode
- streaming Telegram message edits
- final production cutover of Hermes delivery before parity proof exists


Exact bootstrap strings
- Unauthorized chat exact reply:
  - `This chat is not authorized yet. Chat ID: <chat_id>. Ask the operator to add it in Agent Hub.`
- Unsupported non-text exact reply:
  - `This bot supports text messages only in v1.`
- `/reset` exact reply:
  - `Conversation reset. Your next text message will start a fresh Jenny conversation.`
- Allowed `/start` exact template:
  - `Jenny connected.
Chat ID: <chat_id>
Reports bound: <yes|no>
Send a message to talk to Jenny. Use /status for config/runtime state. Use /reset to start a fresh conversation.`
- Allowed `/status` exact template:
  - `Chat ID: <chat_id>
Allowed: yes
Reports bound: <yes|no>
Runner status: <status>
Current session id: <session_id|none>`

Exact config precedence and normalization
- Effective value resolution is fixed per field: non-blank env override first, else stored credential, else unset.
- Source labels are fixed:
  - `env` when the effective non-blank env override wins
  - `stored` when the stored value wins
  - `null` when nothing effective exists
- `PUT /api/admin/telegram/config` only mutates stored values for keys present in the request.
- `null` clears the stored value for that key.
- Blank string inputs are normalized to clear/unset.
- `allowed_chat_ids` normalization trims items, drops blanks, de-duplicates while preserving first-seen order.
- Malformed stored/env allowlist JSON must surface `allowlist_error = 'allowed_chat_ids must be a JSON array'`.
- Empty normalized allowlist degrades reported status but must not block bot polling startup.

Exact admin API contract
- Status/config endpoints:
  - `GET /api/admin/telegram/status`
  - `PUT /api/admin/telegram/config`
- Exact response shape:
  - `configured: bool`
  - `bot_token_source: 'env' | 'stored' | null`
  - `bot_username: str | null`
  - `allowed_chat_ids: list[str]`
  - `allowed_chat_ids_source: 'env' | 'stored' | null`
  - `report_chat_id: str | null`
  - `report_chat_id_source: 'env' | 'stored' | null`
  - `runner_status: 'not_configured' | 'unknown' | 'polling' | 'degraded'`
  - `last_poll_at: str | null`
  - `last_error: str | null`
- Exact request shape for `PUT /config`:
  - `bot_token?: str | null`
  - `allowed_chat_ids?: list[str] | null`
  - `report_chat_id?: str | null`
- Runner-status semantics:
  - `not_configured` when no token is effective
  - `degraded` when allowlist parsing fails or the normalized allowlist is empty
  - `unknown` when config is otherwise valid but no runner heartbeat exists yet
  - otherwise use the heartbeat payload's runner status

Exact sender fallback and threading rules
- Sender tries MarkdownV2 first.
- Parse fallback is triggered only when Telegram rejects the Markdown send with an error message containing `parse` or `markdown` (case-insensitive).
- On that failure, strip MarkdownV2 formatting/escapes, re-chunk through the same UTF-16-aware path, and retry once with `parse_mode=None`.
- If the plain-text retry fails, surface the failure normally.
- First DM chunk sends with `reply_to_message_id` set to the inbound message.
- Later DM chunks omit `reply_to_message_id` and continue unthreaded.

Exact delivery failure semantics
- For scheduler/manual-trigger `delivery=telegram`, the agent-turn result remains authoritative.
- Missing `report_chat_id`, malformed config, or Telegram send failure must not convert a successful agent turn into a failed scheduler/manual-trigger result.
- The workflow logs the delivery problem and leaves the agent-turn output/session result intact.
- The one-shot report script is different: missing token/report chat or send failure is a hard script error because Telegram delivery is the script's whole job.

Exact invalid-combination handling
- API create/update paths reject `delivery=telegram` when `payload_type != agent_turn`.
- Scheduler/manual-trigger code still guards against legacy invalid rows by logging and skipping Telegram delivery instead of throwing.

Verification substitute when live Telegram canary is unavailable
- Required substitute proof:
  - report-script `--dry-run`
  - renderer/delivery mocked-bot tests
  - bot bootstrap/session tests
  - scheduler/manual-trigger Telegram delivery tests
  - admin/config precedence tests
  - systemd template/script tests
- A live native send canary is supplemental proof when credentials/chat binding are available, not the sole acceptable closeout artifact.

Rollout activation boundary
- Canonical `agent-hub-telegram-bot.service` and `agent-hub-telegram-status-report.timer` install disabled by default in this task.
- Do not enable them until the operator intentionally cuts over and the old sidecar/Hermes poller path is stopped or otherwise isolated.
- Avoid duplicate pollers, duplicate recurring sends, or two Telegram owners racing at once.


Exact canonical env/config namespace
- Env override names are fixed:
  - `AGENT_HUB_TELEGRAM_BOT_TOKEN`
  - `AGENT_HUB_TELEGRAM_ALLOWED_CHAT_IDS`
  - `AGENT_HUB_TELEGRAM_REPORT_CHAT_ID`
- Stored credential namespace is fixed:
  - provider `_system_telegram_bot`
  - credential type `bot_token`
  - credential type `allowed_chat_ids`
  - credential type `report_chat_id`
- Whitespace-only scalar env values normalize to unset.
- Env allowlist text is parsed with the same JSON-array normalizer as stored config.
- Malformed env or stored allowlist JSON must produce `allowlist_error = 'allowed_chat_ids must be a JSON array'`.

Exact runner heartbeat contract
- Redis key is fixed:
  - `agent-hub:telegram:bot:status`
- Exact heartbeat payload fields:
  - `runner_status`
  - `last_poll_at`
  - `last_error`
  - `updated_at`
  - `pid`
  - `bot_username`
- Timestamp format is UTC ISO-8601.
- Allowed runner statuses for this task:
  - `not_configured`
  - `unknown`
  - `polling`
  - `degraded`
- Read semantics:
  - missing heartbeat => `unknown` when config is otherwise valid
  - malformed/non-dict heartbeat payload => `runner_status='degraded'`, `last_error='malformed heartbeat payload'`, and null timestamp/username fields
  - stale heartbeat has no separate automatic status downgrade in this task; operators read age from `last_poll_at` / `updated_at`
- `bot_username` source is fixed: it comes only from successful Telegram `getMe()` captured by the bot runner heartbeat. It is `null` before first successful handshake or when heartbeat is absent/malformed.

Exact admin authorization scope
- `/api/admin/telegram/*` uses the same internal-only guard as the rest of `/api/admin`.
- Required header:
  - `X-Agent-Hub-Internal: <internal service secret>`
- Missing/invalid internal header must yield the standard `403` `internal_only` response.
- No separate public auth path is introduced for Telegram config/status in this task.


Exact chat-id typing and malformed-env precedence
- `allowed_chat_ids` normalize to strings everywhere.
- Request/env/stored array items may begin as strings or integers.
- Each item is cast to string, trimmed, blanks dropped, duplicates removed after normalization, and the response shape is always `list[str]`.
- Incoming Telegram `chat_id` values are cast to string before allowlist membership checks.
- `report_chat_id` may begin as string or integer, normalizes to trimmed string, stores as string, and is exposed to callers as `str | null`.
- Blank `report_chat_id` clears/unsets the stored value.
- Malformed `AGENT_HUB_TELEGRAM_ALLOWED_CHAT_IDS` env JSON still wins precedence over stored values; canonical behavior is degraded-empty-effective-allowlist plus `allowlist_error`, not fallback to stored allowlists.

Exact persistence impact for scheduler delivery enum
- Live inspection for this task found `persona_scheduled_jobs.delivery` is plain `varchar` and there is no delivery-specific DB constraint.
- Default expectation: adding `telegram` to the allowed logical enum requires no migration.
- If later inspection during implementation finds a contradictory live DB constraint, stop and add a narrow prerequisite migration plus task-log note before continuing.

Exact Telegram dependency and helper CLI contract
- Canonical backend dependency is `python-telegram-bot>=22.6,<23`.
- `configure_telegram_bot.py` flags are fixed:
  - `--token`
  - repeated `--allowed-chat-id`
  - `--report-chat-id`
  - `--clear-token`
  - `--clear-allowed-chat-ids`
  - `--clear-report-chat-id`
- Clear flags override corresponding set flags for the same field.
- With no mutation flags, the script prints current Telegram status as JSON to stdout.
- With mutations, the script applies them through the canonical config service, prints resulting status as JSON, exits 0 on success, and is idempotent for repeated identical calls.
- Validation failures exit non-zero with a concise error.


Exact `configured` field meaning
- `configured=true` means an effective bot token exists after env-vs-stored precedence resolution.
- `configured` does not require allowlist validity, report binding, or live heartbeat.
- Allowlist/report/heartbeat problems show up through `runner_status` and `last_error`, not by flipping `configured` false.

Exact report-script CLI contract
- `send_jenny_telegram_status_report.py` flags are fixed:
  - `--dry-run`
  - `--title`
  - `--st-path`
  - `--workdir`
- `--dry-run` does not require live Telegram delivery or report-chat binding.
- `--dry-run` prints the final report body to stdout and exits 0 on success.
- Normal success prints JSON containing at least `sent_chunks` and `title`.
- Generation or delivery failure exits non-zero with a concise error.

Exact runner lifecycle cleanup
- Graceful shutdown after polling started deletes `agent-hub:telegram:bot:status`.
- Startup failure before polling writes explicit `not_configured` or `degraded` payloads instead of clearing to null.
- Hard crashes may leave the last heartbeat payload behind; admin status reads it verbatim under the no-auto-staleness rule.

Exact unauthorized command behavior
- `/start`, `/status`, `/reset`, and plain text from unauthorized chats all return the same frozen unauthorized-chat message.
- Unauthorized commands do not call `/api/complete`.
- Unauthorized commands do not mutate session/reset keys.
- Unauthorized commands do not reveal privileged status/config details.

Exact install-scope boundary
- Adding canonical Telegram templates does not modify, disable, or auto-start existing Hermes or sidecar Telegram units/timers.
- This task only adds canonical templates plus disabled-by-default activation instructions.


Exact mixed-failure precedence and heartbeat encoding
- `not_configured` wins whenever no effective bot token exists, even if allowlist parsing also fails or the normalized allowlist is empty.
- Allowlist-driven `degraded` only applies when an effective token is present.
- `agent-hub:telegram:bot:status` stores one JSON-serialized object payload, not a Redis hash.
- Any non-JSON or non-object payload is treated as malformed heartbeat and degrades status.

Exact unauthorized non-text precedence
- Authorization check runs before content-type handling.
- Unauthorized chats always receive the frozen unauthorized-chat message, even for stickers/photos/other non-text updates.
- The text-only-v1 unsupported-content reply is only for authorized chats.

Exact admin PUT error and partial-update behavior
- Handler-level Telegram config normalization failures return HTTP 400 with concise `detail` text.
- FastAPI body/schema validation failures before the handler keep the default 422 behavior.
- Omitted keys preserve stored values exactly.
- Only keys present in the request mutate.

Exact shared-path proof requirement
- Tests/verification must prove DM replies and scheduler/report sends call one shared canonical delivery helper implementation.
- Matching visible output alone is not enough proof if code paths fork.
