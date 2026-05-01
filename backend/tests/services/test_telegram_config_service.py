from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.services.telegram_config_service import (
    ALLOWED_CHAT_IDS_TYPE,
    BOT_TOKEN_TYPE,
    REPORT_CHAT_ID_TYPE,
    TELEGRAM_PROVIDER,
    get_telegram_status,
    load_runtime_config,
    normalize_chat_ids,
    update_telegram_config,
)


class TestNormalizeChatIds:
    def test_normalizes_mixed_types_trims_and_dedupes(self) -> None:
        values, error = normalize_chat_ids([123, " 123 ", "456", "", 456, "  "])

        assert values == ["123", "456"]
        assert error is None

    def test_rejects_non_array_json_string(self) -> None:
        values, error = normalize_chat_ids('"123"')

        assert values == []
        assert error == "allowed_chat_ids must be a JSON array"


@pytest.mark.asyncio
async def test_load_runtime_config_prefers_non_blank_env_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.telegram_config_service.settings.agent_hub_telegram_bot_token",
        " env-token ",
    )
    monkeypatch.setattr(
        "app.services.telegram_config_service.settings.agent_hub_telegram_allowed_chat_ids",
        '[123, " 123 ", "456"]',
    )
    monkeypatch.setattr(
        "app.services.telegram_config_service.settings.agent_hub_telegram_report_chat_id",
        " 789 ",
    )
    monkeypatch.setattr(
        "app.services.telegram_config_service._load_stored_value",
        AsyncMock(side_effect=["stored-token", '["999"]', "999"]),
    )

    payload = await load_runtime_config(AsyncMock())

    assert payload == {
        "token": "env-token",
        "allowed_chat_ids": ["123", "456"],
        "report_chat_id": "789",
        "bot_token_source": "env",
        "allowed_chat_ids_source": "env",
        "report_chat_id_source": "env",
        "allowlist_error": None,
    }


@pytest.mark.asyncio
async def test_load_runtime_config_malformed_env_allowlist_blocks_stored_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.telegram_config_service.settings.agent_hub_telegram_bot_token",
        "",
    )
    monkeypatch.setattr(
        "app.services.telegram_config_service.settings.agent_hub_telegram_allowed_chat_ids",
        "not-json",
    )
    monkeypatch.setattr(
        "app.services.telegram_config_service.settings.agent_hub_telegram_report_chat_id",
        "",
    )
    monkeypatch.setattr(
        "app.services.telegram_config_service._load_stored_value",
        AsyncMock(side_effect=["stored-token", '["999"]', "999"]),
    )

    payload = await load_runtime_config(AsyncMock())

    assert payload["token"] == "stored-token"
    assert payload["allowed_chat_ids"] == []
    assert payload["report_chat_id"] == "999"
    assert payload["bot_token_source"] == "stored"
    assert payload["allowed_chat_ids_source"] == "env"
    assert payload["allowlist_error"] == "allowed_chat_ids must be a JSON array"


@pytest.mark.asyncio
async def test_load_runtime_config_treats_blank_stored_scalars_as_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.telegram_config_service.settings.agent_hub_telegram_bot_token",
        "",
    )
    monkeypatch.setattr(
        "app.services.telegram_config_service.settings.agent_hub_telegram_allowed_chat_ids",
        "",
    )
    monkeypatch.setattr(
        "app.services.telegram_config_service.settings.agent_hub_telegram_report_chat_id",
        "",
    )
    monkeypatch.setattr(
        "app.services.telegram_config_service._load_stored_value",
        AsyncMock(side_effect=["  ", '["123"]', "  "]),
    )

    payload = await load_runtime_config(AsyncMock())

    assert payload["token"] is None
    assert payload["allowed_chat_ids"] == ["123"]
    assert payload["report_chat_id"] is None
    assert payload["bot_token_source"] is None
    assert payload["allowed_chat_ids_source"] == "stored"
    assert payload["report_chat_id_source"] is None


@pytest.mark.asyncio
async def test_get_telegram_status_no_token_wins_over_allowlist_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.telegram_config_service.load_runtime_config",
        AsyncMock(
            return_value={
                "token": None,
                "allowed_chat_ids": [],
                "report_chat_id": None,
                "bot_token_source": None,
                "allowed_chat_ids_source": "env",
                "report_chat_id_source": None,
                "allowlist_error": "allowed_chat_ids must be a JSON array",
            }
        ),
    )
    monkeypatch.setattr(
        "app.services.telegram_config_service._load_runner_payload",
        AsyncMock(return_value=None),
    )

    payload = await get_telegram_status(AsyncMock())

    assert payload["configured"] is False
    assert payload["runner_status"] == "not_configured"
    assert payload["last_error"] == "allowed_chat_ids must be a JSON array"


@pytest.mark.asyncio
async def test_get_telegram_status_uses_valid_json_heartbeat(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.telegram_config_service.load_runtime_config",
        AsyncMock(
            return_value={
                "token": "stored-token",
                "allowed_chat_ids": ["123"],
                "report_chat_id": "123",
                "bot_token_source": "stored",
                "allowed_chat_ids_source": "stored",
                "report_chat_id_source": "stored",
                "allowlist_error": None,
            }
        ),
    )
    monkeypatch.setattr(
        "app.services.telegram_config_service._load_runner_payload",
        AsyncMock(
            return_value={
                "runner_status": "polling",
                "last_poll_at": "2026-04-23T01:00:00+00:00",
                "last_error": None,
                "updated_at": "2026-04-23T01:00:00+00:00",
                "pid": 123,
                "bot_username": "jenny_bot",
            }
        ),
    )

    payload = await get_telegram_status(AsyncMock())

    assert payload == {
        "configured": True,
        "bot_token_source": "stored",
        "bot_username": "jenny_bot",
        "allowed_chat_ids": ["123"],
        "allowed_chat_ids_source": "stored",
        "report_chat_id": "123",
        "report_chat_id_source": "stored",
        "runner_status": "polling",
        "last_poll_at": "2026-04-23T01:00:00+00:00",
        "last_error": None,
    }


@pytest.mark.asyncio
async def test_get_telegram_status_degrades_on_malformed_heartbeat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.telegram_config_service.load_runtime_config",
        AsyncMock(
            return_value={
                "token": "stored-token",
                "allowed_chat_ids": ["123"],
                "report_chat_id": "123",
                "bot_token_source": "stored",
                "allowed_chat_ids_source": "stored",
                "report_chat_id_source": "stored",
                "allowlist_error": None,
            }
        ),
    )
    monkeypatch.setattr(
        "app.services.telegram_config_service._load_runner_payload",
        AsyncMock(return_value={"runner_status": "degraded", "last_error": "malformed heartbeat payload"}),
    )

    payload = await get_telegram_status(AsyncMock())

    assert payload["configured"] is True
    assert payload["runner_status"] == "degraded"
    assert payload["last_error"] == "malformed heartbeat payload"
    assert payload["bot_username"] is None
    assert payload["last_poll_at"] is None


@pytest.mark.asyncio
async def test_update_telegram_config_normalizes_and_upserts(monkeypatch: pytest.MonkeyPatch) -> None:
    db = AsyncMock()
    mock_upsert = AsyncMock()
    mock_delete = AsyncMock()
    mock_status = {
        "configured": True,
        "bot_token_source": "stored",
        "bot_username": None,
        "allowed_chat_ids": ["123", "456"],
        "allowed_chat_ids_source": "stored",
        "report_chat_id": "789",
        "report_chat_id_source": "stored",
        "runner_status": "unknown",
        "last_poll_at": None,
        "last_error": None,
    }
    monkeypatch.setattr("app.services.telegram_config_service.upsert_credential", mock_upsert)
    monkeypatch.setattr("app.services.telegram_config_service._delete_stored_value", mock_delete)
    monkeypatch.setattr(
        "app.services.telegram_config_service.get_telegram_status",
        AsyncMock(return_value=mock_status),
    )

    payload = await update_telegram_config(
        db,
        {
            "bot_token": " token ",
            "allowed_chat_ids": [123, " 123 ", "456"],
            "report_chat_id": 789,
        },
    )

    assert payload == mock_status
    mock_upsert.assert_any_await(db, TELEGRAM_PROVIDER, BOT_TOKEN_TYPE, "token")
    mock_upsert.assert_any_await(db, TELEGRAM_PROVIDER, ALLOWED_CHAT_IDS_TYPE, '["123", "456"]')
    mock_upsert.assert_any_await(db, TELEGRAM_PROVIDER, REPORT_CHAT_ID_TYPE, "789")
    mock_delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_telegram_config_clears_present_null_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_delete = AsyncMock()
    monkeypatch.setattr("app.services.telegram_config_service._delete_stored_value", mock_delete)
    monkeypatch.setattr("app.services.telegram_config_service.upsert_credential", AsyncMock())
    monkeypatch.setattr(
        "app.services.telegram_config_service.get_telegram_status",
        AsyncMock(return_value={"configured": False}),
    )

    payload = await update_telegram_config(
        AsyncMock(),
        {"bot_token": None, "allowed_chat_ids": None, "report_chat_id": None},
    )

    assert payload == {"configured": False}
    assert mock_delete.await_args_list[0].args[1] == BOT_TOKEN_TYPE
    assert mock_delete.await_args_list[1].args[1] == ALLOWED_CHAT_IDS_TYPE
    assert mock_delete.await_args_list[2].args[1] == REPORT_CHAT_ID_TYPE
