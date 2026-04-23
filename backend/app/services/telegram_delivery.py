from __future__ import annotations

from typing import Any

from app.services.telegram_config_service import load_runtime_config
from app.services.telegram_renderer import _strip_mdv2, chunk_for_telegram, format_markdown_v2


async def send_rendered_message(
    *,
    bot: Any,
    chat_id: str,
    text: str,
    reply_to_message_id: int | None = None,
    disable_link_previews: bool = False,
    limit: int = 4096,
) -> int:
    if not text or not text.strip():
        return 0

    formatted = format_markdown_v2(text)
    if formatted is None:
        return 0

    markdown_chunks = chunk_for_telegram(formatted, limit=limit, markdown=True)
    sent = 0

    for index, chunk in enumerate(markdown_chunks):
        reply_to = reply_to_message_id if index == 0 else None
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=chunk,
                parse_mode="MarkdownV2",
                reply_to_message_id=reply_to,
                disable_web_page_preview=disable_link_previews,
            )
            sent += 1
            continue
        except Exception as exc:
            lowered = str(exc).lower()
            if "parse" not in lowered and "markdown" not in lowered:
                raise

        plain_chunks = chunk_for_telegram(_strip_mdv2(chunk), limit=limit, markdown=False)
        for plain_index, plain_chunk in enumerate(plain_chunks):
            await bot.send_message(
                chat_id=chat_id,
                text=plain_chunk,
                parse_mode=None,
                reply_to_message_id=reply_to if plain_index == 0 else None,
                disable_web_page_preview=disable_link_previews,
            )
            sent += 1

    return sent


async def send_configured_report(*, db: Any, title: str | None, body: str) -> int:
    runtime_config = await load_runtime_config(db)
    token = runtime_config.get("token")
    report_chat_id = runtime_config.get("report_chat_id")
    if not token:
        raise RuntimeError("bot_token missing")
    if not report_chat_id:
        raise RuntimeError("report_chat_id missing")

    text = body.strip()
    if title:
        title_line = title.strip()
        text = f"{title_line}\n\n{text}" if text else title_line

    from telegram import Bot

    bot = Bot(token=token)
    return await send_rendered_message(
        bot=bot,
        chat_id=str(report_chat_id),
        text=text,
        disable_link_previews=True,
    )
