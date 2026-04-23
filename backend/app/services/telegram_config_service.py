from __future__ import annotations

import json
from typing import Any

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.credential_manager import get_credential_manager
from app.services.credential_upsert import upsert_credential
from app.storage.credentials import (
    delete_credential_async,
    get_credential_async,
    list_credentials_async,
)

TELEGRAM_PROVIDER = "_system_telegram_bot"
BOT_TOKEN_TYPE = "bot_token"
ALLOWED_CHAT_IDS_TYPE = "allowed_chat_ids"
REPORT_CHAT_ID_TYPE = "report_chat_id"
RUNNER_STATUS_KEY = "agent-hub:telegram:bot:status"
_ALLOWLIST_ERROR = "allowed_chat_ids must be a JSON array"


def _source_label(value: str | None, *, env_value: str | None) -> str | None:
    if env_value:
        return "env"
    if value:
        return "stored"
    return None


def _normalize_stringish(value: str | int | None) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def normalize_chat_ids(raw: list[str | int] | tuple[str | int, ...] | str | None) -> tuple[list[str], str | None]:
    if raw is None:
        return [], None

    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return [], _ALLOWLIST_ERROR
    else:
        parsed = list(raw)

    if not isinstance(parsed, list):
        return [], _ALLOWLIST_ERROR

    normalized: list[str] = []
    seen: set[str] = set()
    for item in parsed:
        text = _normalize_stringish(item)
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return normalized, None


async def _load_stored_value(db: AsyncSession, credential_type: str) -> str | None:
    return await get_credential_async(db, TELEGRAM_PROVIDER, credential_type)


async def _delete_stored_value(db: AsyncSession, credential_type: str) -> None:
    credentials = await list_credentials_async(db, provider=TELEGRAM_PROVIDER)
    for credential in credentials:
        if credential.credential_type == credential_type:
            await delete_credential_async(db, credential.id)
            get_credential_manager().remove(TELEGRAM_PROVIDER, credential_type)
            return


async def _load_runner_payload() -> dict[str, Any] | None:
    client = aioredis.from_url(settings.agent_hub_redis_url, decode_responses=True)
    try:
        raw = await client.get(RUNNER_STATUS_KEY)
    finally:
        await client.close()

    if not raw:
        return None

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {
            "runner_status": "degraded",
            "last_error": "malformed heartbeat payload",
            "updated_at": None,
        }

    if not isinstance(payload, dict):
        return {
            "runner_status": "degraded",
            "last_error": "malformed heartbeat payload",
            "updated_at": None,
        }

    return payload


async def load_runtime_config(db: AsyncSession) -> dict[str, Any]:
    env_token = _normalize_stringish(getattr(settings, "agent_hub_telegram_bot_token", ""))
    env_allowed = _normalize_stringish(getattr(settings, "agent_hub_telegram_allowed_chat_ids", ""))
    env_report_chat = _normalize_stringish(getattr(settings, "agent_hub_telegram_report_chat_id", ""))

    stored_token = await _load_stored_value(db, BOT_TOKEN_TYPE)
    stored_allowed = await _load_stored_value(db, ALLOWED_CHAT_IDS_TYPE)
    stored_report_chat = await _load_stored_value(db, REPORT_CHAT_ID_TYPE)

    token = env_token or stored_token
    allowlist_source_value = env_allowed if env_allowed is not None else stored_allowed
    allowed_chat_ids, allowlist_error = normalize_chat_ids(allowlist_source_value)
    report_chat_id = env_report_chat or _normalize_stringish(stored_report_chat)

    return {
        "token": token,
        "allowed_chat_ids": allowed_chat_ids,
        "report_chat_id": report_chat_id,
        "bot_token_source": _source_label(token, env_value=env_token),
        "allowed_chat_ids_source": _source_label(allowlist_source_value, env_value=env_allowed),
        "report_chat_id_source": _source_label(report_chat_id, env_value=env_report_chat),
        "allowlist_error": allowlist_error,
    }


async def get_telegram_status(db: AsyncSession) -> dict[str, Any]:
    runtime_config = await load_runtime_config(db)
    token = runtime_config["token"]
    allowed_chat_ids = runtime_config["allowed_chat_ids"]
    report_chat_id = runtime_config["report_chat_id"]
    runner_payload = await _load_runner_payload()

    bot_username = None
    last_poll_at = None
    last_error = runtime_config["allowlist_error"]

    if not token:
        runner_status = "not_configured"
    elif runtime_config["allowlist_error"] or not allowed_chat_ids:
        runner_status = "degraded"
        last_error = runtime_config["allowlist_error"] or "allowed_chat_ids is empty"
    elif runner_payload is None:
        runner_status = "unknown"
    else:
        runner_status = str(runner_payload.get("runner_status") or "degraded")
        bot_username = _normalize_stringish(runner_payload.get("bot_username"))
        last_poll_at = _normalize_stringish(runner_payload.get("last_poll_at"))
        payload_error = _normalize_stringish(runner_payload.get("last_error"))
        if payload_error:
            last_error = payload_error

    return {
        "configured": bool(token),
        "bot_token_source": runtime_config["bot_token_source"],
        "bot_username": bot_username,
        "allowed_chat_ids": allowed_chat_ids,
        "allowed_chat_ids_source": runtime_config["allowed_chat_ids_source"],
        "report_chat_id": report_chat_id,
        "report_chat_id_source": runtime_config["report_chat_id_source"],
        "runner_status": runner_status,
        "last_poll_at": last_poll_at,
        "last_error": last_error,
    }


async def update_telegram_config(db: AsyncSession, payload: dict[str, Any]) -> dict[str, Any]:
    if "bot_token" in payload:
        value = _normalize_stringish(payload.get("bot_token"))
        if value is None:
            await _delete_stored_value(db, BOT_TOKEN_TYPE)
        else:
            await upsert_credential(db, TELEGRAM_PROVIDER, BOT_TOKEN_TYPE, value)

    if "allowed_chat_ids" in payload:
        raw_allowed = payload.get("allowed_chat_ids")
        if raw_allowed is None:
            await _delete_stored_value(db, ALLOWED_CHAT_IDS_TYPE)
        else:
            normalized, error = normalize_chat_ids(list(raw_allowed))
            if error:
                raise ValueError(error)
            await upsert_credential(
                db,
                TELEGRAM_PROVIDER,
                ALLOWED_CHAT_IDS_TYPE,
                json.dumps(normalized),
            )

    if "report_chat_id" in payload:
        report_chat_id = _normalize_stringish(payload.get("report_chat_id"))
        if report_chat_id is None:
            await _delete_stored_value(db, REPORT_CHAT_ID_TYPE)
        else:
            await upsert_credential(db, TELEGRAM_PROVIDER, REPORT_CHAT_ID_TYPE, report_chat_id)

    return await get_telegram_status(db)
