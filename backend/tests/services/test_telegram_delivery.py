from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.services.telegram_delivery import send_rendered_message


@pytest.mark.asyncio
async def test_send_rendered_message_uses_markdown_and_link_preview_flag() -> None:
    bot = AsyncMock()

    sent = await send_rendered_message(
        bot=bot,
        chat_id="123",
        text="**bold**",
        reply_to_message_id=42,
        disable_link_previews=True,
    )

    assert sent == 1
    kwargs = bot.send_message.await_args.kwargs
    assert kwargs["chat_id"] == "123"
    assert kwargs["parse_mode"] == "MarkdownV2"
    assert kwargs["reply_to_message_id"] == 42
    assert kwargs["disable_web_page_preview"] is True


@pytest.mark.asyncio
async def test_send_rendered_message_falls_back_to_plain_text_on_markdown_parse_error() -> None:
    bot = AsyncMock()
    bot.send_message.side_effect = [Exception("can't parse entities"), AsyncMock(message_id=1)]

    sent = await send_rendered_message(
        bot=bot,
        chat_id="123",
        text="**bold**",
        disable_link_previews=False,
    )

    assert sent == 1
    first = bot.send_message.await_args_list[0].kwargs
    second = bot.send_message.await_args_list[1].kwargs
    assert first["parse_mode"] == "MarkdownV2"
    assert second["parse_mode"] is None
    assert second["text"] == "bold"
    assert second["disable_web_page_preview"] is False


@pytest.mark.asyncio
async def test_send_rendered_message_threads_only_first_chunk() -> None:
    bot = AsyncMock()

    sent = await send_rendered_message(
        bot=bot,
        chat_id="123",
        text="x" * 25,
        reply_to_message_id=77,
        limit=12,
    )

    assert sent == bot.send_message.await_count
    assert sent > 1
    assert bot.send_message.await_args_list[0].kwargs["reply_to_message_id"] == 77
    assert bot.send_message.await_args_list[1].kwargs["reply_to_message_id"] is None
