"""Exact notification retirement leaves generic automation history intact."""

import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings
from app.db import _get_async_url

PROFILE_ID = "1b94e5ba-f7fa-4635-9f94-9bcc3ec34c31"
WORKFLOW = "neri/notification_maintenance"
GENERIC_WORKFLOW = "portfolio-ai/retrain_ml"


def _migration():
    path = Path(__file__).parents[1] / "alembic/versions/7e31a9c4f602_retire_neri_notification_automation.py"
    spec = importlib.util.spec_from_file_location("neri_notification_retirement", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def _apply(connection):
    with Operations.context(MigrationContext.configure(connection)):
        _migration().upgrade()


def _snapshot(connection, tables):
    return {name: connection.execute(sa.select(table)).all() for name, table in tables.items()}


@pytest.fixture
def database():
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    definitions = sa.Table(
        "automation_definitions", metadata,
        sa.Column("workflow_key", sa.String, primary_key=True),
        sa.Column("version", sa.Integer, primary_key=True),
        *[sa.Column(name, sa.String) for name in ("owner_project_id", "dispatch_kind", "dispatch_target")],
        sa.Column("config_schema", sa.JSON),
    )
    profiles = sa.Table(
        "automation_profiles", metadata, sa.Column("id", sa.String, primary_key=True),
        *[sa.Column(name, sa.String) for name in ("project_id", "workflow_key", "subject_id")],
        sa.Column("definition_version", sa.Integer), sa.Column("config", sa.JSON),
    )
    revisions = sa.Table(
        "automation_profile_revisions", metadata, sa.Column("id", sa.String, primary_key=True),
        sa.Column("profile_id", sa.ForeignKey("automation_profiles.id", ondelete="CASCADE")),
        sa.Column("snapshot", sa.JSON),
    )
    runs = sa.Table(
        "automation_runs", metadata, sa.Column("id", sa.String, primary_key=True),
        sa.Column("profile_id", sa.ForeignKey("automation_profiles.id", ondelete="RESTRICT")),
        *[sa.Column(name, sa.String) for name in ("project_id", "workflow_key", "status")],
        sa.Column("definition_version", sa.Integer), sa.Column("owner_receipt", sa.JSON),
    )
    policies = sa.Table(
        "automation_project_policies", metadata, sa.Column("project_id", sa.String, primary_key=True),
        sa.Column("config", sa.JSON), sa.Column("revision", sa.Integer),
    )
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        metadata.create_all(connection)
        connection.execute(definitions.insert(), [
            {"workflow_key": WORKFLOW, "version": 1, "owner_project_id": "neri", "dispatch_kind": "callback", "dispatch_target": "/automations/dispatch/notification_maintenance", "config_schema": {"legacy": "notification"}},
            {"workflow_key": GENERIC_WORKFLOW, "version": 2, "owner_project_id": "portfolio-ai", "dispatch_kind": "callback", "dispatch_target": "/automations/dispatch/retrain_ml", "config_schema": {"generic": [1, 2]}},
        ])
        connection.execute(profiles.insert(), [
            {"id": PROFILE_ID, "project_id": "neri", "workflow_key": WORKFLOW, "subject_id": None, "definition_version": 1, "config": {"push_enabled": False}},
            {"id": "generic", "project_id": "portfolio-ai", "workflow_key": GENERIC_WORKFLOW, "subject_id": None, "definition_version": 2, "config": {"exact": "keep"}},
        ])
        connection.execute(revisions.insert(), [
            {"id": "retired-revision", "profile_id": PROFILE_ID, "snapshot": {"project_id": "neri", "workflow_key": WORKFLOW, "definition_version": 1, "subject_id": None}},
            {"id": "generic-revision", "profile_id": "generic", "snapshot": {"exact": "generic history"}},
        ])
        connection.execute(runs.insert(), [
            {"id": f"retired-{index}", "profile_id": PROFILE_ID, "project_id": "neri", "workflow_key": WORKFLOW,
             "definition_version": 1, "status": "succeeded", "owner_receipt": (
                 {"delivered": 0} if index < 15 else {"status": "succeeded", "owner_run_id": str(index)}
             )}
            for index in range(47)
        ] + [{"id": "generic-run", "profile_id": "generic", "project_id": "portfolio-ai", "workflow_key": GENERIC_WORKFLOW,
              "definition_version": 2, "status": "running", "owner_receipt": {"exact": "receipt"}}])
        connection.execute(policies.insert(), [
            {"project_id": "neri", "config": {"exact": "neri policy"}, "revision": 7},
            {"project_id": "portfolio-ai", "config": {"exact": "generic policy"}, "revision": 12},
        ])
        yield connection, metadata.tables
    engine.dispose()


def _assert_exact_retirement(connection, tables, before):
    _apply(connection)
    _apply(connection)
    after = _snapshot(connection, tables)
    for name in ("automation_definitions", "automation_profiles", "automation_profile_revisions", "automation_runs"):
        assert after[name] == [before[name][-1]]
    assert after["automation_project_policies"] == before["automation_project_policies"]


def test_retirement_is_exact_repeatable_and_preserves_generic_rows_and_neri_policy(database):
    connection, tables = database
    _assert_exact_retirement(connection, tables, _snapshot(connection, tables))


@pytest.mark.parametrize("drift", [
    "definition_version", "definition_owner", "definition_target", "definition_kind",
    "extra_profile", "profile_owner", "profile_workflow", "profile_version", "profile_subject",
    "revision", "run_owner", "run_profile", "run_workflow", "run_version",
    "admitted", "dispatching", "accepted", "running", "unknown", "failed", "cancelled",
])
def test_retirement_refuses_drift_before_any_mutation(database, drift):
    connection, tables = database
    definitions = tables["automation_definitions"]
    profiles = tables["automation_profiles"]
    revisions = tables["automation_profile_revisions"]
    runs = tables["automation_runs"]
    if drift.startswith("definition_"):
        key, value = {
            "definition_version": ("version", 2), "definition_owner": ("owner_project_id", "other"),
            "definition_target": ("dispatch_target", "/different"), "definition_kind": ("dispatch_kind", "hatchet"),
        }[drift]
        connection.execute(definitions.update().where(definitions.c.workflow_key == WORKFLOW).values({key: value}))
    elif drift == "extra_profile":
        connection.execute(profiles.insert(), {"id": "extra", "project_id": "neri", "workflow_key": WORKFLOW, "definition_version": 1})
    elif drift.startswith("profile_"):
        key, value = {
            "profile_owner": ("project_id", "other"), "profile_workflow": ("workflow_key", "other/work"),
            "profile_version": ("definition_version", 2), "profile_subject": ("subject_id", "persona:1"),
        }[drift]
        connection.execute(profiles.update().where(profiles.c.id == PROFILE_ID).values({key: value}))
    elif drift == "revision":
        connection.execute(revisions.update().where(revisions.c.profile_id == PROFILE_ID).values(snapshot={"project_id": "other"}))
    else:
        key, value = {
            "run_owner": ("project_id", "other"), "run_profile": ("profile_id", "generic"),
            "run_workflow": ("workflow_key", "other/work"), "run_version": ("definition_version", 2),
        }.get(drift, ("status", drift))
        connection.execute(runs.update().where(runs.c.id == "retired-0").values({key: value}))
    before = _snapshot(connection, tables)
    with pytest.raises(RuntimeError, match=r"identity|extra profile|terminal receipt"):
        _apply(connection)
    assert _snapshot(connection, tables) == before


def test_retirement_tolerates_missing_tables():
    engine = sa.create_engine("sqlite://")
    with engine.connect() as connection:
        _apply(connection)
        _apply(connection)
        assert sa.inspect(connection).get_table_names() == []
    engine.dispose()


def test_downgrade_cannot_recreate_notification_product():
    with pytest.raises(RuntimeError, match="intentionally not recreated"):
        _migration().downgrade()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_retirement_against_isolated_postgresql_schema(database):
    source, tables = database
    url = _get_async_url(settings.agent_hub_db_url)
    assert make_url(url).database == "agent_hub_test"
    engine = create_async_engine(url)
    schema = "neri_notification_retirement_" + uuid4().hex
    try:
        async with engine.connect() as connection:
            await connection.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
            await connection.execute(sa.text(f'SET LOCAL search_path TO "{schema}"'))

            def exercise(sync):
                metadata = next(iter(tables.values())).metadata
                metadata.create_all(sync)
                for table in metadata.sorted_tables:
                    rows = [dict(row) for row in source.execute(sa.select(table)).mappings()]
                    if rows:
                        sync.execute(table.insert(), rows)
                _assert_exact_retirement(sync, tables, _snapshot(sync, tables))

            await connection.run_sync(exercise)
            await connection.rollback()
    finally:
        await engine.dispose()
