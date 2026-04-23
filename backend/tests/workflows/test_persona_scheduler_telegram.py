from __future__ import annotations

import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_maybe_send_delivery_telegram_skips_non_telegram_delivery() -> None:
    from app.workflows.persona_scheduler import _maybe_send_delivery_telegram

    job = SimpleNamespace(id="job-1", name="Digest", payload_type="agent_turn", delivery="none")

    with patch(
        "app.workflows.persona_scheduler.send_rendered_message",
        new=AsyncMock(),
    ) as mock_send:
        await _maybe_send_delivery_telegram(job, "hello")

    mock_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_maybe_send_delivery_telegram_skips_non_agent_turn_payload() -> None:
    from app.workflows.persona_scheduler import _maybe_send_delivery_telegram

    job = SimpleNamespace(id="job-1", name="Digest", payload_type="push", delivery="telegram")

    with patch(
        "app.workflows.persona_scheduler.send_rendered_message",
        new=AsyncMock(),
    ) as mock_send:
        await _maybe_send_delivery_telegram(job, "hello")

    mock_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_maybe_send_delivery_telegram_sends_to_report_chat_when_configured() -> None:
    from app.workflows.persona_scheduler import _maybe_send_delivery_telegram

    job = SimpleNamespace(id="job-1", name="Daily digest", payload_type="agent_turn", delivery="telegram")
    fake_db = AsyncMock()

    class _SessionCtx:
        async def __aenter__(self):
            return fake_db

        async def __aexit__(self, exc_type, exc, tb):
            return False

    mock_bot_cls = MagicMock(return_value=object())
    with (
        patch("app.workflows.persona_scheduler.async_session", lambda: _SessionCtx()),
        patch(
            "app.workflows.persona_scheduler.load_runtime_config",
            new=AsyncMock(return_value={"token": "token", "report_chat_id": "123"}),
        ),
        patch.dict(sys.modules, {"telegram": types.SimpleNamespace(Bot=mock_bot_cls)}),
        patch(
            "app.workflows.persona_scheduler.send_rendered_message",
            new=AsyncMock(return_value=1),
        ) as mock_send,
    ):
        await _maybe_send_delivery_telegram(job, "hello")

    mock_bot_cls.assert_called_once_with(token="token")
    mock_send.assert_awaited_once()
    await_args = mock_send.await_args
    assert await_args is not None
    kwargs = await_args.kwargs
    assert kwargs["chat_id"] == "123"
    assert kwargs["text"] == "hello"
    assert kwargs["disable_link_previews"] is True


@pytest.mark.asyncio
async def test_maybe_send_delivery_telegram_best_effort_on_missing_report_chat() -> None:
    from app.workflows.persona_scheduler import _maybe_send_delivery_telegram

    job = SimpleNamespace(id="job-1", name="Daily digest", payload_type="agent_turn", delivery="telegram")
    fake_db = AsyncMock()

    class _SessionCtx:
        async def __aenter__(self):
            return fake_db

        async def __aexit__(self, exc_type, exc, tb):
            return False

    with (
        patch("app.workflows.persona_scheduler.async_session", lambda: _SessionCtx()),
        patch(
            "app.workflows.persona_scheduler.load_runtime_config",
            new=AsyncMock(return_value={"token": "token", "report_chat_id": None}),
        ),
        patch(
            "app.workflows.persona_scheduler.logger.warning",
        ) as mock_warning,
    ):
        await _maybe_send_delivery_telegram(job, "hello")

    mock_warning.assert_called()
