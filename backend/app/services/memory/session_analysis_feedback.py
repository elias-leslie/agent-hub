"""Feedback tag processing helpers for session_analysis."""

from __future__ import annotations

import logging

from sqlalchemy import select

from .citation_parser import parse_feedback_tags
from .session_queries import extract_feedback_from_events

logger = logging.getLogger(__name__)


async def fetch_feedback_tag_dicts(
    session_id: str,
    feedback_tags: list[str] | None,
) -> list[dict]:
    """Return list of tag dicts either from CC transcript strings or session events."""
    if feedback_tags is not None:
        tag_dicts: list[dict] = []
        for raw in feedback_tags:
            if not isinstance(raw, str):
                continue
            result = parse_feedback_tags(raw)
            for tag in result.tags:
                tag_dicts.append(tag.model_dump())
        return tag_dicts
    return await extract_feedback_from_events(session_id)


async def persist_feedback_items(
    db,
    session_id: str,
    tag_dicts: list[dict],
    project_id: str,
    agent_slug: str,
) -> int:
    """Write feedback items to DB, skipping duplicates. Returns count created."""
    from app.models.feedback import FeedbackItem
    from app.services.feedback_storage import (
        create_feedback_item,
        find_duplicate_candidates,
        vote_on_item,
    )

    existing_query = select(
        FeedbackItem.component_id, FeedbackItem.feedback_type
    ).where(FeedbackItem.created_by_session_id == session_id)
    existing_rows = await db.execute(existing_query)
    existing_keys = {(r.component_id, r.feedback_type) for r in existing_rows}

    created = 0
    voted = 0
    for tag_dict in tag_dicts:
        key = (tag_dict["component_id"], tag_dict["feedback_type"])
        if key in existing_keys:
            continue
        desc = tag_dict.get("description", "")
        title = desc[:120] if desc else f"{tag_dict['feedback_type']} on {tag_dict['component_id']}"
        duplicates = await find_duplicate_candidates(
            db,
            component_id=tag_dict["component_id"],
            feedback_type=tag_dict["feedback_type"],
            project_id=project_id,
            title=title,
            limit=1,
        )
        if duplicates:
            vote = await vote_on_item(
                db,
                item_id=str(duplicates[0].id),
                session_id=session_id,
                comment=desc or None,
                agent_slug=agent_slug,
            )
            existing_keys.add(key)
            if vote is not None:
                voted += 1
            continue
        await create_feedback_item(
            db,
            component_id=tag_dict["component_id"],
            feedback_type=tag_dict["feedback_type"],
            title=title,
            description=desc or None,
            project_id=project_id,
            session_id=session_id,
            agent_slug=agent_slug,
            session_type="inline_tag",
        )
        existing_keys.add(key)
        created += 1

    if created or voted:
        await db.commit()
        logger.info(
            "Tracked session feedback for %s: created=%d voted=%d",
            session_id,
            created,
            voted,
        )

    return created
