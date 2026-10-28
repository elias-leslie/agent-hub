"""A-Term's client and permission row move to aico; the client keeps its id and still allows a-term."""

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
async def test_a_term_client_and_permission_move_to_aico() -> None:
    async with _get_engine().connect() as connection:
        assert (await connection.execute(sa.text("SELECT current_database()"))).scalar() == "agent_hub_test"
        try:
            await connection.run_sync(_migrate)
        finally:
            await connection.rollback()


def _migrate(conn) -> None:
    path = Path(__file__).resolve().parents[2] / "alembic/versions/f1b3d5a7c9e2_aico_merge_client_and_scopes.py"
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    conn.execute(sa.text("DELETE FROM clients WHERE display_name IN ('a-term', 'aico') AND client_type = 'service'"))
    conn.execute(sa.text("DELETE FROM project_permissions WHERE project_id IN ('a-term', 'aico')"))
    client_id = str(uuid.uuid4())
    conn.execute(
        sa.text("INSERT INTO clients (id, display_name, client_type, status, allowed_projects)"
                " VALUES (:id, 'a-term', 'service', 'active', :allowed)"),
        {"id": client_id, "allowed": json.dumps(["a-term"])},
    )
    conn.execute(
        sa.text("INSERT INTO project_permissions (project_id, root_path)"
                " VALUES ('a-term', '/srv/workspaces/projects/a-term')")
    )
    with Operations.context(MigrationContext.configure(conn)):
        migration.upgrade()
    name, allowed = conn.execute(
        sa.text("SELECT display_name, allowed_projects FROM clients WHERE id = :id"), {"id": client_id}
    ).one()
    assert (name, json.loads(allowed)) == ("aico", ["aico", "a-term"])
    assert conn.execute(
        sa.text("SELECT project_id, root_path FROM project_permissions WHERE project_id IN ('a-term', 'aico')")
    ).all() == [("aico", "/srv/workspaces/projects/aico")]
