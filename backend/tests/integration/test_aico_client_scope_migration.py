"""The aico client stops allowing the legacy a-term project; downgrade puts it back."""

from __future__ import annotations

import importlib.util
import json
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.db import _get_engine


@pytest.mark.integration
@pytest.mark.asyncio
async def test_aico_client_drops_a_term_scope() -> None:
    async with _get_engine().connect() as connection:
        assert (await connection.execute(sa.text("SELECT current_database()"))).scalar() == "agent_hub_test"
        try:
            await connection.run_sync(_migrate)
        finally:
            await connection.rollback()


def _migrate(conn) -> None:
    path = Path(__file__).resolve().parents[2] / "alembic/versions/a7c2e4f6b8d0_aico_client_drops_legacy_a_term_scope.py"
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    conn.execute(sa.text("DELETE FROM clients WHERE display_name = 'aico' AND client_type = 'service'"))
    client_id = str(uuid.uuid4())
    conn.execute(
        sa.text("INSERT INTO clients (id, display_name, client_type, status, allowed_projects)"
                " VALUES (:id, 'aico', 'service', 'active', :allowed)"),
        {"id": client_id, "allowed": json.dumps(["aico", "a-term"])},
    )

    def allowed() -> list[str]:
        value = conn.execute(sa.text("SELECT allowed_projects FROM clients WHERE id = :id"), {"id": client_id}).scalar()
        return json.loads(value)

    with Operations.context(MigrationContext.configure(conn)):
        migration.upgrade()
        assert allowed() == ["aico"]
        migration.downgrade()
        assert allowed() == ["aico", "a-term"]
