"""Seed the session-analysis prompt into the prompts table.

Run with: python -m scripts.seed_session_analysis_prompt

Uses upsert pattern: creates if absent, skips if slug already exists.
The prompt is editable in the Agent Hub UI after seeding.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.models.prompt import Prompt

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SLUG = "session-analysis"
NAME = "Session Analysis (Summary + Ratings)"
DESCRIPTION = (
    "Combined prompt for session summary generation and memory rating. "
    "Produces SUMMARY, OUTCOME, DECISIONS, TOOLS, FILES, TOPICS, GIT_DIGEST, and RATINGS "
    "in a single Gemini Flash call. Template variables: {session_id}, {project_id}, "
    "{agent_slug}, {transcript}, {git_context_block}, {memory_block}."
)

CONTENT = """\
Analyze this AI coding session. Focus on discoveries, failure modes, and workarounds — not process narrative.

Session: {session_id}
Project: {project_id}
Agent: {agent_slug}

Transcript:
{transcript}
{git_context_block}
{memory_block}
Respond in this EXACT format (no markdown, no extra text):
SUMMARY: <1-3 sentence summary focusing on what was accomplished or discovered, key failures, and workarounds found>
OUTCOME: <completed | failed | partial>
DECISIONS: <comma-separated list of key decisions made, or NONE>
TOOLS: <comma-separated list of unique tools used, or NONE>
FILES: <comma-separated list of files modified, or NONE>
TOPICS: <comma-separated list of topics/technologies, or NONE>
GIT_DIGEST: <1-line digest of commits relevant to this session, or NONE>
RATINGS: <one "[uuid8] helpful|harmful|neutral" per line, or NONE if no memories listed above>"""


async def main() -> None:
    db_url = settings.agent_hub_db_url.replace("postgresql://", "postgresql+asyncpg://")
    engine = create_async_engine(db_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as db:
        result = await db.execute(select(Prompt).where(Prompt.slug == SLUG))
        existing = result.scalar_one_or_none()

        if existing:
            logger.info("Prompt '%s' already exists (id=%d), skipping", SLUG, existing.id)
        else:
            prompt = Prompt(
                slug=SLUG,
                name=NAME,
                content=CONTENT,
                description=DESCRIPTION,
                is_global=False,
            )
            db.add(prompt)
            await db.commit()
            logger.info("Created prompt: %s", SLUG)

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
