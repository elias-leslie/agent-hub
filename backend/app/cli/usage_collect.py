"""One usage pass for the systemd timer: read new Claude Code / Codex transcript lines into the ledger
and take an OpenCode Go quota reading.

    python -m app.cli.usage_collect
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging

from app.db import async_session
from app.services.credential_manager import get_credential_manager
from app.services.model_catalog_service import refresh_runtime_model_catalog
from app.services.subscription_accounting.collector import collect

logger = logging.getLogger(__name__)


async def run(*, replay: str | None = None) -> dict:
    async with async_session() as db:
        await refresh_runtime_model_catalog(db)
        await get_credential_manager().load(db)  # the OpenCode Go key is a stored credential, not an env var
        result = await collect(db, min_interval_s=0, replay=replay)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay", metavar="NAME", help="Reconcile native usage; reuse NAME to resume bounded passes (no retention pruning)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    print(json.dumps(asyncio.run(run(replay=args.replay))), flush=True)


if __name__ == "__main__":
    main()
