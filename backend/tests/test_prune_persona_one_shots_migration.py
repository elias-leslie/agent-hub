"""Exercise the exact-pair Persona cleanup against PostgreSQL transactions."""

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings
from app.db import _get_async_url


def _migration():
    path = Path(__file__).parents[1] / "alembic/versions/6d7e8f9a0b1c_prune_obsolete_persona_one_shots.py"
    spec = importlib.util.spec_from_file_location("prune_persona_one_shots", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


async def _create_tables(connection):
    await connection.execute(text("""
        CREATE TEMP TABLE automation_profiles (
            id text PRIMARY KEY, project_id text, workflow_key text, subject_id text,
            source_ref text, schedule_type text, schedule_value text, enabled boolean,
            clock_owner text, max_runs integer, run_count integer, revision integer,
            imported_unreviewed_count integer, last_run_at timestamptz
        )
    """))
    await connection.execute(text("""
        CREATE TEMP TABLE persona_scheduled_jobs (
            id uuid PRIMARY KEY, persona_id integer, schedule_type text,
            schedule_value text, enabled boolean, max_runs integer,
            run_count integer, last_run_at timestamptz
        )
    """))
    await connection.execute(text("""
        CREATE TEMP TABLE automation_profile_revisions (
            profile_id text REFERENCES automation_profiles(id) ON DELETE CASCADE
        )
    """))
    await connection.execute(text("CREATE TEMP TABLE automation_runs (profile_id text)"))


def _apply(migration, sync_connection):
    with Operations.context(MigrationContext.configure(sync_connection)):
        migration.upgrade()


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("missing_owner", [False, True])
async def test_persona_cleanup_deletes_exact_pairs_or_rolls_back_on_partial_set(missing_owner):
    migration = _migration()
    url = _get_async_url(settings.agent_hub_db_url)
    assert make_url(url).database == "agent_hub_test"
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            await _create_tables(connection)
            await connection.run_sync(lambda sync: _apply(migration, sync))  # Empty database is a no-op.
            rows = []
            owners = []
            for index, (profile_id, owner_id) in enumerate(migration.EXPECTED_PAIRS):
                count = 0 if index < 4 else 1
                stamp = None if count == 0 else datetime(2026, 3, 6, tzinfo=UTC)
                rows.append({
                    "id": profile_id, "source_ref": f"persona:{owner_id}",
                    "run_count": count, "last_run_at": stamp,
                })
                owners.append({"id": UUID(owner_id), "run_count": count, "last_run_at": stamp})
            await connection.execute(text("""
                INSERT INTO automation_profiles VALUES (
                    :id, 'agent-hub', 'agent-hub.persona_job', 'persona:1',
                    :source_ref, 'at', '2026-03-05T12:00:00Z', false,
                    'central', 1, :run_count, 2, 0, :last_run_at
                )
            """), rows)
            await connection.execute(text("""
                INSERT INTO persona_scheduled_jobs VALUES (
                    :id, 1, 'at', '2026-03-05T12:00:00Z', false, 1,
                    :run_count, :last_run_at
                )
            """), owners)
            await connection.execute(text("""
                INSERT INTO automation_profile_revisions (profile_id)
                SELECT id FROM automation_profiles CROSS JOIN generate_series(1, 2)
            """))
            await connection.execute(text("""
                INSERT INTO automation_profiles VALUES (
                    'unrelated', 'agent-hub', 'agent-hub.persona_job', 'persona:1',
                    'persona:unrelated', 'every', '900000', true,
                    'central', NULL, 0, 1, 0, NULL
                )
            """))
            if missing_owner:
                await connection.execute(text("DELETE FROM persona_scheduled_jobs WHERE id = :id"), {
                    "id": owners[0]["id"],
                })
                with pytest.raises(RuntimeError, match="incomplete"):
                    await connection.run_sync(lambda sync: _apply(migration, sync))
                assert (await connection.execute(text(
                    "SELECT count(*) FROM automation_profiles"
                ))).scalar_one() == 53
            else:
                await connection.run_sync(lambda sync: _apply(migration, sync))
                assert (await connection.execute(text(
                    "SELECT id FROM automation_profiles"
                ))).scalars().all() == ["unrelated"]
                assert (await connection.execute(text(
                    "SELECT count(*) FROM persona_scheduled_jobs"
                ))).scalar_one() == 0
                assert (await connection.execute(text(
                    "SELECT count(*) FROM automation_profile_revisions"
                ))).scalar_one() == 0
            await connection.rollback()
    finally:
        await engine.dispose()
