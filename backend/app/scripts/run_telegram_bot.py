from __future__ import annotations

import asyncio

from app.services.telegram_bot_service import AgentHubTelegramBot


async def _run() -> int:
    bot = AgentHubTelegramBot()
    try:
        return await bot.run_polling()
    finally:
        await bot.close()


def main() -> None:
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":  # pragma: no cover
    main()
