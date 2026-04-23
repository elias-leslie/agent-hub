from __future__ import annotations

import argparse
import asyncio
import json

from app.db import async_session
from app.services.telegram_config_service import get_telegram_status, update_telegram_config


def build_payload(args: argparse.Namespace) -> dict[str, object]:
    payload: dict[str, object] = {}
    if args.token is not None:
        payload["bot_token"] = args.token
    if args.allowed_chat_ids is not None:
        payload["allowed_chat_ids"] = args.allowed_chat_ids
    if args.report_chat_id is not None:
        payload["report_chat_id"] = args.report_chat_id
    if args.clear_token:
        payload["bot_token"] = None
    if args.clear_allowed_chat_ids:
        payload["allowed_chat_ids"] = None
    if args.clear_report_chat_id:
        payload["report_chat_id"] = None
    return payload


async def run_command(args: argparse.Namespace) -> None:
    payload = build_payload(args)
    async with async_session() as db:
        if payload:
            status = await update_telegram_config(db, payload)
        else:
            status = await get_telegram_status(db)
    print(json.dumps(status))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Configure Agent Hub Telegram bot state")
    parser.add_argument("--token")
    parser.add_argument("--allowed-chat-id", dest="allowed_chat_ids", action="append")
    parser.add_argument("--report-chat-id")
    parser.add_argument("--clear-token", action="store_true")
    parser.add_argument("--clear-allowed-chat-ids", action="store_true")
    parser.add_argument("--clear-report-chat-id", action="store_true")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    asyncio.run(run_command(args))


if __name__ == "__main__":  # pragma: no cover
    main()
