"""Pi session types must survive PostgreSQL writes and SQLAlchemy reads."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.db import _get_engine
from app.models import Session


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pi_session_type_round_trip() -> None:
    async with _get_engine().connect() as connection:
        assert (await connection.execute(sa.text("SELECT current_database()"))).scalar() == "agent_hub_test"
        try:
            await connection.run_sync(_round_trip)
        finally:
            await connection.rollback()


def _round_trip(conn) -> None:
    table = sa.Table(
        "pi_session_type_probe", sa.MetaData(),
        sa.Column("session_type", Session.__table__.c.session_type.type),
        prefixes=["TEMPORARY"], postgresql_on_commit="DROP",
    )
    table.create(conn, checkfirst=True)
    conn.execute(table.insert().values(session_type="pi"))
    assert conn.execute(sa.select(table.c.session_type)).scalar_one() == "pi"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pi_session_type_migration_preserves_existing_values() -> None:
    async with _get_engine().connect() as connection:
        assert (await connection.execute(sa.text("SELECT current_database()"))).scalar() == "agent_hub_test"
        try:
            await connection.run_sync(_migrate_legacy_type)
        finally:
            await connection.rollback()


def _migrate_legacy_type(conn) -> None:
    path = Path(__file__).resolve().parents[2] / "alembic/versions/e3a7c9d1f502_add_pi_session_type.py"
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    # Explicit pg_temp lookup shadows the public enum for this transaction only.
    conn.execute(sa.text("CREATE TYPE pg_temp.session_type_enum AS ENUM ('completion', 'claude_code')"))
    conn.execute(sa.text("SET LOCAL search_path TO pg_temp, public"))
    with Operations.context(MigrationContext.configure(conn)):
        migration.upgrade()
        migration.upgrade()
        migration.downgrade()
    values = conn.execute(sa.text(
        "SELECT enumlabel FROM pg_enum WHERE enumtypid = 'pg_temp.session_type_enum'::regtype ORDER BY enumsortorder"
    )).scalars().all()
    assert values == ["completion", "claude_code", "pi"]
