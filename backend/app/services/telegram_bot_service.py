from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

import httpx
import redis.asyncio as aioredis

from app.config import settings
from app.db import async_session
from app.services.first_party_client_service import reconcile_first_party_clients
from app.services.telegram_config_service import (
    RUNNER_STATUS_KEY,
    get_telegram_status,
    load_runtime_config,
)
from app.services.telegram_delivery import send_rendered_message

logger = logging.getLogger(__name__)

BLOCKED_CHAT_TEMPLATE = "This chat is not authorized yet. Chat ID: {chat_id}. Ask the operator to add it in Agent Hub."
TEXT_ONLY_V1_REPLY = "This bot supports text messages only in v1."
RESET_CONFIRMATION = "Conversation reset. Your next text message will start a fresh Jenny conversation."
SESSION_KEY_PREFIX = "agent-hub:telegram:chat"
TELEGRAM_CHAT_MAX_TURNS = 8
TELEGRAM_CONNECT_TIMEOUT_SECONDS = 10.0
TELEGRAM_READ_TIMEOUT_SECONDS = 30.0
TELEGRAM_WRITE_TIMEOUT_SECONDS = 10.0
TELEGRAM_POOL_TIMEOUT_SECONDS = 10.0


def blocked_chat_text(chat_id: str) -> str:
    return BLOCKED_CHAT_TEMPLATE.format(chat_id=chat_id)


def text_only_v1_reply() -> str:
    return TEXT_ONLY_V1_REPLY


def reset_confirmation_text() -> str:
    return RESET_CONFIRMATION


def allowed_start_text(*, chat_id: str, reports_bound: bool) -> str:
    bound = "yes" if reports_bound else "no"
    return (
        "Jenny connected.\n"
        f"Chat ID: {chat_id}\n"
        f"Reports bound: {bound}\n"
        "Send a message to talk to Jenny. Use /status for config/runtime state. Use /reset to start a fresh conversation."
    )


def current_session_id_text(session_id: str | None) -> str:
    return f"Current session id: {session_id or 'none'}"


def _sort_key(session: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(session.get("updated_at") or ""),
        str(session.get("created_at") or ""),
        str(session.get("id") or ""),
    )


def select_latest_session_id(sessions: list[dict[str, Any]]) -> str | None:
    if not sessions:
        return None
    latest = max(sessions, key=_sort_key)
    session_id = latest.get("id")
    return str(session_id) if session_id else None


class AgentHubTelegramBot:
    def __init__(self) -> None:
        self.base_url = f"http://127.0.0.1:{settings.port}"
        self.client_id = settings.agent_hub_telegram_client_id
        self.request_source = "telegram"
        self.redis = aioredis.from_url(settings.agent_hub_redis_url, decode_responses=True)
        self.bot_username: str | None = None

    def _headers(self) -> dict[str, str]:
        return {
            "X-Client-Id": self.client_id,
            "X-Request-Source": self.request_source,
            "X-Source-Client": "agent-hub-telegram-bot",
            "X-Source-Path": "backend/app/scripts/run_telegram_bot.py",
        }

    def _build_application(self, token: str) -> Any:
        from telegram.ext import Application

        return (
            Application.builder()
            .token(token)
            .connect_timeout(TELEGRAM_CONNECT_TIMEOUT_SECONDS)
            .read_timeout(TELEGRAM_READ_TIMEOUT_SECONDS)
            .write_timeout(TELEGRAM_WRITE_TIMEOUT_SECONDS)
            .pool_timeout(TELEGRAM_POOL_TIMEOUT_SECONDS)
            .get_updates_connect_timeout(TELEGRAM_CONNECT_TIMEOUT_SECONDS)
            .get_updates_read_timeout(TELEGRAM_READ_TIMEOUT_SECONDS)
            .get_updates_write_timeout(TELEGRAM_WRITE_TIMEOUT_SECONDS)
            .get_updates_pool_timeout(TELEGRAM_POOL_TIMEOUT_SECONDS)
            .build()
        )

    def _session_key(self, chat_id: str) -> str:
        return f"{SESSION_KEY_PREFIX}:{chat_id}:session_id"

    def _force_new_key(self, chat_id: str) -> str:
        return f"{SESSION_KEY_PREFIX}:{chat_id}:force_new"

    async def close(self) -> None:
        await self.redis.close()

    async def write_runner_status(
        self,
        *,
        runner_status: str,
        last_error: str | None = None,
        bot_username: str | None = None,
    ) -> None:
        payload = {
            "runner_status": runner_status,
            "last_poll_at": None,
            "last_error": last_error,
            "updated_at": datetime.now(UTC).isoformat(),
            "pid": os.getpid(),
            "bot_username": bot_username or self.bot_username,
        }
        await self.redis.set(RUNNER_STATUS_KEY, json.dumps(payload))

    async def heartbeat(self) -> None:
        payload = await self.redis.get(RUNNER_STATUS_KEY)
        try:
            data = json.loads(payload) if payload else {}
        except json.JSONDecodeError:
            data = {}
        if not isinstance(data, dict):
            data = {}
        now = datetime.now(UTC).isoformat()
        data.update(
            {
                "runner_status": "polling",
                "last_poll_at": now,
                "updated_at": now,
                "last_error": None,
                "pid": os.getpid(),
                "bot_username": self.bot_username,
            }
        )
        await self.redis.set(RUNNER_STATUS_KEY, json.dumps(data))

    async def clear_runner_status(self) -> None:
        await self.redis.delete(RUNNER_STATUS_KEY)

    async def _load_config(self) -> dict[str, Any]:
        async with async_session() as db:
            return await load_runtime_config(db)

    async def _status_payload(self) -> dict[str, Any]:
        async with async_session() as db:
            return await get_telegram_status(db)

    async def _is_allowed(self, chat_id: str) -> bool:
        config = await self._load_config()
        return chat_id in set(config.get("allowed_chat_ids") or [])

    async def _reply(self, update: Any, text: str, *, bot: Any) -> int:
        if update.effective_message is None or update.effective_chat is None:
            return 0
        return await send_rendered_message(
            bot=bot,
            chat_id=str(update.effective_chat.id),
            text=text,
            reply_to_message_id=getattr(update.effective_message, "message_id", None),
            disable_link_previews=False,
        )

    async def _fetch_latest_session_id(self, external_id: str) -> str | None:
        async with httpx.AsyncClient(base_url=self.base_url, headers=self._headers(), timeout=60) as client:
            response = await client.get(
                "/api/sessions",
                params={"project_id": "agent-hub", "external_id": external_id, "page_size": 50},
            )
            response.raise_for_status()
            payload = response.json()
            return select_latest_session_id(payload.get("sessions") or [])

    async def _resolve_session_id(self, chat_id: str, external_id: str) -> str | None:
        force_new = await self.redis.get(self._force_new_key(chat_id))
        if force_new:
            return None
        current = await self.redis.get(self._session_key(chat_id))
        if current:
            return current
        latest = await self._fetch_latest_session_id(external_id)
        if latest:
            await self.redis.set(self._session_key(chat_id), latest)
        return latest

    async def _store_session_id(self, chat_id: str, session_id: str) -> None:
        await self.redis.set(self._session_key(chat_id), session_id)
        await self.redis.delete(self._force_new_key(chat_id))

    async def _mark_force_new(self, chat_id: str) -> None:
        await self.redis.delete(self._session_key(chat_id))
        await self.redis.set(self._force_new_key(chat_id), "1")

    async def _complete_text(self, *, chat_id: str, text: str) -> tuple[str, str]:
        external_id = f"telegram:dm:{chat_id}"
        session_id = await self._resolve_session_id(chat_id, external_id)
        payload: dict[str, Any] = {
            "messages": [{"role": "user", "content": text}],
            "project_id": "agent-hub",
            "agent_slug": "persona",
            "external_id": external_id,
            "use_memory": True,
            "enable_caching": False,
            "skip_cache": True,
            "max_turns": TELEGRAM_CHAT_MAX_TURNS,
            "execute_tools": True,
            "enable_programmatic_tools": True,
        }
        if session_id:
            payload["session_id"] = session_id

        async with httpx.AsyncClient(base_url=self.base_url, headers=self._headers(), timeout=300) as client:
            response = await client.post("/api/complete", json=payload)
            response.raise_for_status()
            data = response.json()

        new_session_id = str(data["session_id"])
        await self._store_session_id(chat_id, new_session_id)
        content = data.get("content")
        if isinstance(content, str):
            return content, new_session_id
        if isinstance(content, list):
            parts = [
                str(block.get("text", "")).strip()
                for block in content
                if isinstance(block, dict)
                and block.get("type") == "text"
                and str(block.get("text", "")).strip()
            ]
            return "\n\n".join(parts), new_session_id
        return "", new_session_id

    async def handle_start(self, update: Any, context: Any) -> None:
        chat_id = str(update.effective_chat.id)
        if not await self._is_allowed(chat_id):
            await self._reply(update, blocked_chat_text(chat_id), bot=context.bot)
            return
        config = await self._load_config()
        await self._reply(
            update,
            allowed_start_text(chat_id=chat_id, reports_bound=bool(config.get("report_chat_id"))),
            bot=context.bot,
        )

    async def handle_status(self, update: Any, context: Any) -> None:
        chat_id = str(update.effective_chat.id)
        if not await self._is_allowed(chat_id):
            await self._reply(update, blocked_chat_text(chat_id), bot=context.bot)
            return
        config = await self._load_config()
        status = await self._status_payload()
        current_session_id = await self.redis.get(self._session_key(chat_id))
        lines = [
            f"Chat ID: {chat_id}",
            "Allowed: yes",
            f"Reports bound: {'yes' if bool(config.get('report_chat_id')) else 'no'}",
            f"Runner status: {status.get('runner_status', 'unknown')}",
            current_session_id_text(current_session_id),
        ]
        await self._reply(update, "\n".join(lines), bot=context.bot)

    async def handle_reset(self, update: Any, context: Any) -> None:
        chat_id = str(update.effective_chat.id)
        if not await self._is_allowed(chat_id):
            await self._reply(update, blocked_chat_text(chat_id), bot=context.bot)
            return
        await self._mark_force_new(chat_id)
        await self._reply(update, reset_confirmation_text(), bot=context.bot)

    async def handle_text(self, update: Any, context: Any) -> None:
        chat_id = str(update.effective_chat.id)
        if not await self._is_allowed(chat_id):
            await self._reply(update, blocked_chat_text(chat_id), bot=context.bot)
            return
        user_text = update.effective_message.text if update.effective_message else ""
        if not user_text or not user_text.strip():
            return
        try:
            reply_text, _session_id = await self._complete_text(chat_id=chat_id, text=user_text)
        except Exception as exc:  # pragma: no cover - runtime safeguard
            logger.exception("Telegram completion failed for chat %s", chat_id)
            await self.write_runner_status(runner_status="degraded", last_error=str(exc))
            await self._reply(update, f"Jenny hit an error: {exc}", bot=context.bot)
            return
        await self.heartbeat()
        await self._reply(update, reply_text or "(no output)", bot=context.bot)

    async def handle_non_text(self, update: Any, context: Any) -> None:
        chat_id = str(update.effective_chat.id)
        if not await self._is_allowed(chat_id):
            await self._reply(update, blocked_chat_text(chat_id), bot=context.bot)
            return
        await self._reply(update, text_only_v1_reply(), bot=context.bot)

    async def heartbeat_job(self, context: Any) -> None:
        _ = context
        await self.heartbeat()

    async def heartbeat_loop(self, *, interval_seconds: float = 30.0) -> None:
        while True:
            await self.heartbeat()
            await asyncio.sleep(interval_seconds)

    async def run_polling(self) -> int:
        async with async_session() as db:
            await reconcile_first_party_clients(db)
            config = await load_runtime_config(db)
        token = config.get("token")
        if not token:
            await self.write_runner_status(runner_status="not_configured", last_error=None)
            return 1
        if config.get("allowlist_error"):
            await self.write_runner_status(
                runner_status="degraded",
                last_error=config.get("allowlist_error"),
            )
            return 1

        from telegram.ext import CommandHandler, MessageHandler, filters

        application = self._build_application(str(token))
        application.add_handler(CommandHandler("start", self.handle_start))
        application.add_handler(CommandHandler("status", self.handle_status))
        application.add_handler(CommandHandler("reset", self.handle_reset))
        application.add_handler(
            MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, self.handle_text)
        )
        application.add_handler(
            MessageHandler(filters.ChatType.PRIVATE & ~filters.TEXT, self.handle_non_text)
        )
        initialized = False
        started = False
        polling_started = False
        heartbeat_task: asyncio.Task[None] | None = None
        try:
            await application.initialize()
            initialized = True
            me = await application.bot.get_me()
            self.bot_username = me.username
            await self.write_runner_status(
                runner_status="polling",
                bot_username=self.bot_username,
                last_error=None,
            )
            await application.start()
            started = True
            if application.updater is None:
                raise RuntimeError("telegram updater unavailable")
            await application.updater.start_polling(drop_pending_updates=False)
            polling_started = True
            await self.heartbeat()
            heartbeat_task = asyncio.create_task(self.heartbeat_loop())
            try:
                while True:
                    await asyncio.sleep(3600)
            finally:  # pragma: no cover - runtime cleanup
                if heartbeat_task is not None:
                    heartbeat_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await heartbeat_task
                await application.updater.stop()
                await application.stop()
                await application.shutdown()
                await self.clear_runner_status()
        except Exception as exc:
            if not polling_started:
                await self.write_runner_status(runner_status="degraded", last_error=str(exc))
                if started:
                    await application.stop()
                if initialized:
                    await application.shutdown()
            raise
