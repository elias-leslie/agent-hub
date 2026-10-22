"""Repair known Codex projection defects from an already validated local source."""

import json

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session
from app.services.event_storage import _build_session_event, get_max_sequence

from ._events import _load_existing_source_events
from .models import NormalizedEvent


async def repair_codex_projection(
    db: AsyncSession, session: Session, events: list[NormalizedEvent], checkpoint: str,
    *, include_messages: bool = False,
) -> tuple[int, list[str], str]:
    """Correct roles and recover errors without replaying tools or live activity.

    The caller holds the session ingestion lock and has verified that this full
    parse ends at the committed cursor. Historical errors append within their
    original turn, retaining their source timestamp and identity.
    """
    types = {"system_message", "error"}
    if not (session.provider_metadata or {}).get("native_observation_namespace"):
        types.update({"native_lifecycle", "native_settings"})
    candidates = [event for event in events if include_messages or event.event_type in types]
    existing = await _load_existing_source_events(
        db, session.id, {event.source_event_id for event in candidates if event.source_event_id},
    )
    updated = 0
    added = []
    sequences: dict[int, int] = {}
    for event in candidates:
        retained = existing.get(event.source_event_id)
        if retained is not None:
            if (
                event.event_type == "system_message"
                and event.role in {"developer", "system"}
                and retained.event_type == "assistant_message"
                and retained.role == "assistant"
            ):
                expected = _build_session_event(
                    session.id, retained.turn, retained.sequence, event.event_type,
                    role=event.role, content=event.content,
                )
                if retained.content != expected.content:
                    raise ValueError("The retained instruction differs from its native source.")
                retained.event_type = event.event_type
                retained.role = event.role
                updated += 1
            continue
        if not event.source_event_id or event.turn is None:
            continue
        if event.event_type == "system_message" and not include_messages:
            continue
        if event.turn not in sequences:
            sequences[event.turn] = await get_max_sequence(db, session.id, event.turn)
        sequences[event.turn] += 1
        values = event.model_dump(exclude={"turn", "sequence", "native_observation"})
        stored = _build_session_event(session.id, event.turn, sequences[event.turn], **values)
        db.add(stored)
        existing[event.source_event_id] = stored
        added.append(stored)
    await db.flush()
    # The next incremental read must allocate past repaired errors and any
    # independently appended hook events, rather than collide and lose an item.
    cursor = json.loads(checkpoint)
    cursor["sequence"] = max(
        cursor["sequence"], await get_max_sequence(db, session.id, cursor["turn"]),
    )
    return updated, [str(event.id) for event in added], json.dumps(cursor)
