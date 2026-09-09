"""Exercise the retirement migration with PostgreSQL's actual JSON column type."""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings
from app.db import _get_async_url


@pytest.mark.integration
@pytest.mark.asyncio
async def test_retirement_preserves_benchmark_history_and_other_metadata():
    url = _get_async_url(settings.agent_hub_db_url)
    assert make_url(url).database == "agent_hub_test"
    path = Path(__file__).parents[1] / "alembic/versions/0c78d126e3ab_retire_caveman_authoring.py"
    spec = importlib.util.spec_from_file_location("retire_caveman", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("CREATE TEMP TABLE sessions (request_source text, provider_metadata json)"))
            await connection.execute(text("CREATE TEMP TABLE compactness_policy (id integer)"))
            await connection.execute(text("""
                INSERT INTO sessions VALUES
                    ('manual/caveman-baseline', '{"existing":"preserved"}'),
                    ('manual/caveman-override', '{"session_kind":"verification"}'),
                    ('ordinary', NULL)
            """))

            def upgrade(sync_connection):
                with Operations.context(MigrationContext.configure(sync_connection)):
                    migration.upgrade()

            await connection.run_sync(upgrade)
            rows = (await connection.execute(text("SELECT request_source, provider_metadata FROM sessions ORDER BY request_source"))).all()
            assert rows == [
                ("manual/caveman-baseline", {"existing": "preserved", "session_kind": "benchmark"}),
                ("manual/caveman-override", {"session_kind": "verification"}),
                ("ordinary", None),
            ]
            assert (await connection.execute(text("SELECT to_regclass('pg_temp.compactness_policy')"))).scalar() is None
            await connection.rollback()
    finally:
        await engine.dispose()
