"""Verify alias retirement on disposable PostgreSQL tables, including rollback."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.db import _get_engine
from app.models.model_catalog import ModelCatalogEntry
from app.services.model_catalog_service import load_seed_catalog


@pytest.mark.integration
@pytest.mark.asyncio
async def test_daybreak_migration_preserves_roles_and_history() -> None:
    async with _get_engine().connect() as connection:
        assert (await connection.execute(sa.text("SELECT current_database()"))).scalar() == "agent_hub_test"
        try:
            await connection.run_sync(_verify_migration)
        finally:
            await connection.rollback()


def _verify_migration(conn) -> None:
    path = Path(__file__).resolve().parents[2] / "alembic/versions/a2d6b8e1f930_pin_daybreak_blue_model.py"
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    old, new = migration._OLD, migration._NEW
    # pg_temp shadows the public tables. No shared fixture or durable row is changed.
    models = sa.Table(
        "models", sa.MetaData(),
        *(sa.Column(
            column.name, column.type, primary_key=column.primary_key,
            nullable=column.nullable, server_default=column.server_default,
        ) for column in ModelCatalogEntry.__table__.columns),
        prefixes=["TEMPORARY"], postgresql_on_commit="DROP",
    )
    models.create(conn)
    conn.execute(sa.text("CREATE TEMP TABLE model_aliases (alias TEXT PRIMARY KEY, model_id TEXT REFERENCES models(id), updated_at TIMESTAMPTZ) ON COMMIT DROP"))
    conn.execute(sa.text("CREATE TEMP TABLE agents (slug TEXT PRIMARY KEY, primary_model_id TEXT, fallback_models JSON, escalation_model_id TEXT, version INT, updated_at TIMESTAMPTZ) ON COMMIT DROP"))
    conn.execute(sa.text("CREATE TEMP TABLE daybreak_history (model TEXT) ON COMMIT DROP"))
    seed = next(row for row in load_seed_catalog()["models"] if row["id"] == new)
    previous = {**seed, "id": old, "upstream_id": None, "availability": "previous", "is_active": True}
    conn.execute(models.insert().values(**previous))
    conn.execute(sa.text("INSERT INTO model_aliases VALUES ('codex-daybreak', :old, NOW())"), {"old": old})
    conn.execute(sa.text(
        "INSERT INTO agents VALUES ('primary', :old, '[]', NULL, 1, NOW()), "
        "('fallback', 'other', CAST(:fallbacks AS JSON), :old, 1, NOW()), "
        "('unrelated', 'other', '[]', NULL, 1, NOW())"
    ), {"old": old, "fallbacks": '["other", "' + old + '"]'})
    conn.execute(sa.text("INSERT INTO daybreak_history VALUES (:old)"), {"old": old})

    with Operations.context(MigrationContext.configure(conn)):
        migration.upgrade()
        pinned = conn.execute(sa.select(models).where(models.c.id == new)).mappings().one()
        assert pinned["upstream_id"] == "gpt-5.6-sol"
        assert pinned["access_programs"] == {"cyber": "daybreak_blue"}
        assert pinned["score_coding"] == previous["score_coding"]
        assert pinned["cost_input_per_m"] == previous["cost_input_per_m"]
        assert conn.execute(sa.text("SELECT model_id FROM model_aliases")).scalar() == new
        rows = {r["slug"]: r for r in conn.execute(sa.text("SELECT * FROM agents")).mappings()}
        assert rows["primary"]["primary_model_id"] == new
        assert rows["fallback"]["fallback_models"] == ["other", new]
        assert rows["fallback"]["escalation_model_id"] == new
        assert rows["unrelated"]["version"] == 1
        assert conn.execute(sa.text("SELECT model FROM daybreak_history")).scalar() == old
        assert conn.execute(sa.select(models.c.is_active).where(models.c.id == old)).scalar() is False
        migration.downgrade()
        assert conn.execute(sa.text("SELECT model_id FROM model_aliases")).scalar() == old
        assert conn.execute(sa.select(models.c.is_active).where(models.c.id == old)).scalar() is True
        assert conn.execute(sa.select(models.c.is_active).where(models.c.id == new)).scalar() is False
        migration.upgrade()
        assert conn.execute(sa.text("SELECT model_id FROM model_aliases")).scalar() == new
