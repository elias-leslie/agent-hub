"""One usage pass for the systemd timer: read new Claude Code / Codex transcript lines into the ledger,
then push an owner alert when spend runs far above its own normal.

    python -m app.cli.usage_collect
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging

from app.db import async_session
from app.services.model_catalog_service import refresh_runtime_model_catalog
from app.services.subscription_accounting.collector import _alert, collect
from app.services.usage_costs import spend_alerts

logger = logging.getLogger(__name__)
SPEND_ALERT_COOLDOWN_S = 24 * 3600


async def run(*, replay: str | None = None) -> dict:
    async with async_session() as db:
        await refresh_runtime_model_catalog(db)
        result = await collect(db, min_interval_s=0, replay=replay)
    if replay is not None or result.get("skipped"):
        return result
    async with async_session() as db:
        alerts = await spend_alerts(db)
    for alert in alerts:
        await _alert(alert.message, title="Agent spend running high", key=alert.key,
                     cooldown=SPEND_ALERT_COOLDOWN_S, open_url=alert.open_url)
    result["spend_alerts"] = len(alerts)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay", metavar="NAME", help="Reconcile native usage; reuse NAME to resume bounded passes (no retention pruning)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    print(json.dumps(asyncio.run(run(replay=args.replay))), flush=True)


if __name__ == "__main__":
    main()
