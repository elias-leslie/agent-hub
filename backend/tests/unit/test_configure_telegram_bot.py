from __future__ import annotations

import argparse
import json
from unittest.mock import AsyncMock

import pytest

from app.scripts.configure_telegram_bot import build_payload, run_command


def test_build_payload_collects_set_flags() -> None:
    args = argparse.Namespace(
        token="token-123",
        allowed_chat_ids=["123", "456"],
        report_chat_id="789",
        clear_token=False,
        clear_allowed_chat_ids=False,
        clear_report_chat_id=False,
    )

    assert build_payload(args) == {
        "bot_token": "token-123",
        "allowed_chat_ids": ["123", "456"],
        "report_chat_id": "789",
    }


def test_build_payload_clear_flags_override_set_values() -> None:
    args = argparse.Namespace(
        token="token-123",
        allowed_chat_ids=["123"],
        report_chat_id="789",
        clear_token=True,
        clear_allowed_chat_ids=True,
        clear_report_chat_id=True,
    )

    assert build_payload(args) == {
        "bot_token": None,
        "allowed_chat_ids": None,
        "report_chat_id": None,
    }


@pytest.mark.asyncio
async def test_run_command_without_mutations_prints_status_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    status = {"configured": False, "runner_status": "not_configured"}
    fake_session = AsyncMock()

    class _SessionCtx:
        async def __aenter__(self):
            return fake_session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("app.scripts.configure_telegram_bot.async_session", lambda: _SessionCtx())
    monkeypatch.setattr("app.scripts.configure_telegram_bot.get_telegram_status", AsyncMock(return_value=status))
    monkeypatch.setattr("app.scripts.configure_telegram_bot.update_telegram_config", AsyncMock())

    args = argparse.Namespace(
        token=None,
        allowed_chat_ids=None,
        report_chat_id=None,
        clear_token=False,
        clear_allowed_chat_ids=False,
        clear_report_chat_id=False,
    )

    await run_command(args)

    captured = capsys.readouterr()
    assert json.loads(captured.out) == status


@pytest.mark.asyncio
async def test_run_command_with_mutations_uses_update_and_prints_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    status = {"configured": True, "runner_status": "unknown"}
    fake_session = AsyncMock()
    update_mock = AsyncMock(return_value=status)

    class _SessionCtx:
        async def __aenter__(self):
            return fake_session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("app.scripts.configure_telegram_bot.async_session", lambda: _SessionCtx())
    monkeypatch.setattr("app.scripts.configure_telegram_bot.get_telegram_status", AsyncMock())
    monkeypatch.setattr("app.scripts.configure_telegram_bot.update_telegram_config", update_mock)

    args = argparse.Namespace(
        token="token-123",
        allowed_chat_ids=["123"],
        report_chat_id="789",
        clear_token=False,
        clear_allowed_chat_ids=False,
        clear_report_chat_id=False,
    )

    await run_command(args)

    captured = capsys.readouterr()
    assert json.loads(captured.out) == status
    update_mock.assert_awaited_once_with(
        fake_session,
        {"bot_token": "token-123", "allowed_chat_ids": ["123"], "report_chat_id": "789"},
    )
