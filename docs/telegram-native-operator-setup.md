# Native Agent Hub Telegram Operator Setup

Canonical runtime lives in `/srv/workspaces/projects/agent-hub`. The sidecar repo `/srv/workspaces/projects/agent-hub-telegram-bot-v1` is donor/reference only.

## BotFather

1. Create or reuse a bot with Telegram BotFather.
2. Keep the bot token out of git and shell history where possible.
3. DM the bot with `/start` once. If the chat id is not allowlisted, the bot replies with the chat id to add.

## Configure

Preferred stored-credential path:

```bash
cd /srv/workspaces/projects/agent-hub/backend
.venv/bin/python -m app.scripts.configure_telegram_bot \
  --token "$AGENT_HUB_TELEGRAM_BOT_TOKEN" \
  --allowed-chat-id "$TELEGRAM_CHAT_ID" \
  --report-chat-id "$TELEGRAM_CHAT_ID"
```

Status only:

```bash
cd /srv/workspaces/projects/agent-hub/backend
.venv/bin/python -m app.scripts.configure_telegram_bot
```

Environment overrides, highest precedence:

```bash
AGENT_HUB_TELEGRAM_BOT_TOKEN=...
AGENT_HUB_TELEGRAM_ALLOWED_CHAT_IDS='["123456789"]'
AGENT_HUB_TELEGRAM_REPORT_CHAT_ID=123456789
```

## Run

Manual bot worker:

```bash
cd /srv/workspaces/projects/agent-hub/backend
.venv/bin/python -m app.scripts.run_telegram_bot
```

Dry-run report generation without Telegram send:

```bash
cd /srv/workspaces/projects/agent-hub/backend
.venv/bin/python -m app.scripts.send_jenny_telegram_status_report --dry-run
```

## Systemd Cutover

Templates live in `scripts/systemd/` and are disabled by default. Install them only after replacing `__PROJECT_ROOT__` with `/srv/workspaces/projects/agent-hub`.

Do not enable the native poller while the legacy sidecar poller is still active. Cutover order:

1. Stop or isolate the legacy `agent-hub-telegram-bot-v1` poller/timer.
2. Start `agent-hub-telegram-bot.service` from canonical Agent Hub.
3. Verify `/api/admin/telegram/status` reports `runner_status=polling`.
4. Enable the canonical status-report timer only after one manual report send succeeds.

Deferred v1 scope: groups, forum topics, media, voice notes, webhook mode, callback queries, inline mode, and streaming edit UX.
