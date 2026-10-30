"""Trim the parent copies of child events that ``child_session_update`` events used to carry in full.

Each update copied the child event's text twice: into its content ("Child session <id> update: <text>") and into
``tool_output.child_event_content``. The child session keeps that event itself (``tool_output.child_event_id``
points at it), so this drops ``child_event_content`` and cuts the content's text to
``settings.child_session_update_preview_chars``, as new updates are now stored. An update whose child event is
gone is left whole: it is the only copy. Batches commit one at a time.

Run with: python -m scripts.compact_child_session_updates [--dry-run] [--batch N]
"""

import argparse
import asyncio
from typing import Any, cast

from sqlalchemy import CursorResult, text

from app.config import settings
from app.db import async_session

_CANDIDATES = """
    FROM session_events se
    WHERE se.event_type = 'child_session_update'
      AND (se.tool_output ? 'child_event_content' OR length(se.content) > strpos(se.content, ' update: ') + 8 + :limit)
      AND EXISTS (SELECT 1 FROM session_events c WHERE c.id = (se.tool_output ->> 'child_event_id')::uuid)
"""

_UPDATE = text(
    f"""
    WITH batch AS (SELECT se.id {_CANDIDATES} LIMIT :batch)
    UPDATE session_events se
    SET tool_output = se.tool_output - 'child_event_content',
        content = left(se.content, strpos(se.content, ' update: ') + 8 + :limit)
    FROM batch WHERE se.id = batch.id
    """
)


async def compact(dry_run: bool, batch: int) -> int:
    limit = settings.child_session_update_preview_chars
    async with async_session() as db:
        if dry_run:
            count = (await db.execute(text(f"SELECT count(*) {_CANDIDATES}"), {"limit": limit})).scalar_one()
            print(f"{count} child_session_update events would be trimmed")
            return int(count)
        total = 0
        while True:
            result = await db.execute(_UPDATE, {"limit": limit, "batch": batch})
            updated = cast(CursorResult[Any], result).rowcount
            await db.commit()
            total += updated
            print(f"trimmed {total}", flush=True)
            if updated < batch:
                return total


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--batch", type=int, default=5000)
    args = parser.parse_args()
    asyncio.run(compact(args.dry_run, args.batch))


if __name__ == "__main__":
    main()
