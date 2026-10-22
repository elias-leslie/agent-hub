"""Native Pi metadata refreshes must not roll back an ingestion cursor."""

import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import delete
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.db import _get_async_url
from app.models import Session
from app.services.session_ingestion.models import SessionUpsertRequest
from app.services.session_ingestion.service import upsert_session


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pi_upsert_preserves_cursor_advanced_after_stale_session_load() -> None:
    url = _get_async_url(settings.agent_hub_db_url)
    assert make_url(url).database == "agent_hub_test", "Integration writes require the isolated test database"
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_id = str(uuid.uuid4())
    try:
        async with factory() as seed:
            seed.add(Session(
                id=session_id, project_id="agent-hub", provider="pi", model="pi/unknown",
                status="active", session_type="agent",
                provider_metadata={"transcript_path": "/fixture/pi.jsonl",
                                   "transcript_ingestion": {"checkpoint": "before"}},
            ))
            await seed.commit()
        async with factory() as stale_db, factory() as advancing_db:
            stale_row = await stale_db.get(Session, session_id)
            advancing_row = await advancing_db.get(Session, session_id)
            assert stale_row is not None and advancing_row is not None
            advancing_row.provider_metadata = {
                **advancing_row.provider_metadata,
                "transcript_ingestion": {"checkpoint": "advanced"},
            }
            await advancing_db.commit()
            with patch("app.services.session_ingestion.service._validate_project_id", return_value=None):
                await upsert_session(stale_db, SessionUpsertRequest(
                    session_id=session_id, project_id="agent-hub", provider="pi",
                    model="pi/unknown", session_type="agent",
                    provider_metadata={"transcript_path": "/fixture/pi.jsonl", "harness": "pi"},
                ))
        async with factory() as verify:
            stored = await verify.get(Session, session_id)
            assert stored is not None and stored.provider_metadata is not None
            assert stored.provider_metadata["transcript_ingestion"]["checkpoint"] == "advanced"
    finally:
        async with factory() as cleanup:
            await cleanup.execute(delete(Session).where(Session.id == session_id))
            await cleanup.commit()
        await engine.dispose()
