"""Exact, guarded retirement preserves generic model and benchmark records."""

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

MODEL_ID = "local/qwen3.8-27b-gsq-rco-iq3_s-mtp"
MODEL_NAME = "Qwen3.8 27B GSQ/RCO IQ3_S (Neri candidate)"
PILOT_ID = "neri-jev-pilot-2026-09"


def _migration():
    path = Path(__file__).parents[1] / "alembic/versions/5b9e4c2a7d10_remove_neri_model_experiments.py"
    spec = importlib.util.spec_from_file_location("neri_model_experiment_retirement", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def _apply(connection):
    with Operations.context(MigrationContext.configure(connection)):
        _migration().upgrade()


@pytest.fixture
def database():
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    budgets = sa.Table("typesafe_jev_budgets", metadata, sa.Column("key", sa.String, primary_key=True))
    dispatches = sa.Table(
        "typesafe_jev_dispatches", metadata, sa.Column("request_id", sa.String, primary_key=True),
        sa.Column("budget_key", sa.ForeignKey("typesafe_jev_budgets.key")),
    )
    models = sa.Table(
        "models", metadata, sa.Column("id", sa.String, primary_key=True),
        *[sa.Column(name, sa.String) for name in ("name", "alias", "provider", "source")],
    )
    aliases = sa.Table(
        "model_aliases", metadata, sa.Column("alias", sa.String, primary_key=True),
        sa.Column("model_id", sa.ForeignKey("models.id")),
    )
    agents = sa.Table(
        "agents", metadata, sa.Column("slug", sa.String, primary_key=True),
        sa.Column("primary_model_id", sa.String), sa.Column("fallback_models", sa.JSON),
        sa.Column("escalation_model_id", sa.String),
    )
    runs = sa.Table(
        "agent_benchmark_runs", metadata, sa.Column("id", sa.String, primary_key=True),
        *[sa.Column(name, sa.String) for name in ("agent_slug", "project_id", "suite_id", "run_kind")],
        sa.Column("models", sa.JSON), sa.Column("metadata", sa.JSON),
    )
    attempts = sa.Table(
        "agent_benchmark_attempts", metadata, sa.Column("id", sa.String, primary_key=True),
        sa.Column("benchmark_run_id", sa.ForeignKey("agent_benchmark_runs.id")),
        sa.Column("raw_content", sa.String),
        *[sa.Column(name, sa.String) for name in ("task_family", "harness_arm", "input_sha256")],
        sa.Column("prompt_revision", sa.Integer),
        *[sa.Column(name, sa.JSON) for name in ("dimension_scores", "runtime_metrics", "safety_failures", "oracle_details", "artifact_identity")],
    )
    sa.Index("ix_agent_benchmark_attempts_task_family", attempts.c.task_family)
    sa.Index("ix_agent_benchmark_attempts_harness_arm", attempts.c.harness_arm)
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        metadata.create_all(connection)
        connection.execute(budgets.insert(), {"key": PILOT_ID})
        connection.execute(dispatches.insert(), {"request_id": "pilot", "budget_key": PILOT_ID})
        connection.execute(models.insert(), [
            {"id": MODEL_ID, "name": MODEL_NAME, "alias": "local/neri-qwen", "provider": "local", "source": "seed"},
            {"id": "local/qwen-generic", "name": "Generic Qwen", "alias": "local/qwen", "provider": "local", "source": "manual"},
        ])
        connection.execute(aliases.insert(), [
            {"alias": "local/neri-qwen", "model_id": MODEL_ID},
            {"alias": "local/qwen", "model_id": "local/qwen-generic"},
        ])
        connection.execute(agents.insert(), {
            "slug": "neri-hunter", "primary_model_id": "codex/gpt-6.1-sol", "fallback_models": [], "escalation_model_id": None,
        })
        connection.execute(runs.insert(), [
            {"id": "retired", "agent_slug": "neri-local-candidate", "project_id": "security-research", "suite_id": "neri-local-worker-heldout", "run_kind": "neri_local_worker_evaluation", "models": [MODEL_ID], "metadata": {"benchmark_type": "neri_local_worker"}},
            {"id": "preflight", "agent_slug": "neri-local-candidate", "project_id": "security-research", "suite_id": "neri-local-study-a", "run_kind": "neri_local_study_preflight", "models": [MODEL_ID], "metadata": {"benchmark_type": "neri_local_worker_study"}},
            {"id": "generic", "agent_slug": "coder", "project_id": "agent-hub", "suite_id": "generic", "run_kind": "evaluation", "models": ["local/qwen-generic"], "metadata": {"control": "unchanged"}},
        ])
        connection.execute(attempts.insert(), [
            {"id": "retired-attempt", "benchmark_run_id": "retired", "raw_content": "experiment", "task_family": "evidence", "dimension_scores": {"x": 1}},
            {"id": "generic-attempt", "benchmark_run_id": "generic", "raw_content": "generic evidence", "task_family": None, "dimension_scores": {}},
        ])
        yield connection, metadata.tables
    engine.dispose()


def test_retirement_is_repeatable_and_preserves_generic_records(database):
    connection, tables = database
    generic_model = connection.execute(sa.select(tables["models"]).where(tables["models"].c.id == "local/qwen-generic")).first()
    generic_run = connection.execute(sa.select(tables["agent_benchmark_runs"]).where(tables["agent_benchmark_runs"].c.id == "generic")).first()
    hunter = connection.execute(sa.select(tables["agents"])).first()
    _apply(connection)
    _apply(connection)
    inspector = sa.inspect(connection)
    assert not inspector.has_table("typesafe_jev_budgets")
    assert not inspector.has_table("typesafe_jev_dispatches")
    assert connection.execute(sa.select(tables["models"])).first() == generic_model
    assert connection.execute(sa.select(tables["agent_benchmark_runs"])).first() == generic_run
    assert connection.execute(sa.select(tables["agents"])).first() == hunter
    assert connection.execute(sa.select(tables["model_aliases"])).all() == [("local/qwen", "local/qwen-generic")]
    assert {column["name"] for column in inspector.get_columns("agent_benchmark_attempts")} == {"id", "benchmark_run_id", "raw_content"}
    assert connection.execute(sa.text("SELECT * FROM agent_benchmark_attempts")).all() == [("generic-attempt", "generic", "generic evidence")]


@pytest.mark.parametrize("drift", ["budget", "model", "agent_primary", "agent_fallback", "agent_escalation", "benchmark", "generic_attempt"])
def test_retirement_stops_before_mutating_unexpected_data(database, drift):
    connection, tables = database
    if drift == "budget":
        connection.execute(tables["typesafe_jev_budgets"].insert(), {"key": "unrelated"})
    elif drift == "model":
        connection.execute(tables["models"].update().where(tables["models"].c.id == MODEL_ID).values(name="Owner replacement"))
    elif drift.startswith("agent_"):
        key, value = {
            "agent_primary": ("primary_model_id", MODEL_ID),
            "agent_fallback": ("fallback_models", [MODEL_ID]),
            "agent_escalation": ("escalation_model_id", MODEL_ID),
        }[drift]
        connection.execute(tables["agents"].update().values({key: value}))
    elif drift == "benchmark":
        connection.execute(tables["agent_benchmark_runs"].update().where(tables["agent_benchmark_runs"].c.id == "retired").values(project_id="unrelated"))
    else:
        connection.execute(tables["agent_benchmark_attempts"].update().where(tables["agent_benchmark_attempts"].c.id == "generic-attempt").values(task_family="generic-work"))
    with pytest.raises(RuntimeError, match=r"unrelated|identity changed|still references|Unrelated benchmark"):
        _apply(connection)
    assert sa.inspect(connection).has_table("typesafe_jev_dispatches")
    assert connection.execute(sa.select(sa.func.count()).select_from(tables["models"])).scalar_one() == 2
    assert connection.execute(sa.select(sa.func.count()).select_from(tables["agent_benchmark_runs"])).scalar_one() == 3


def test_retirement_tolerates_already_absent_experiment_tables():
    engine = sa.create_engine("sqlite://")
    with engine.connect() as connection:
        _apply(connection)
        _apply(connection)
        assert sa.inspect(connection).get_table_names() == []
    engine.dispose()


def test_downgrade_does_not_recreate_experiments():
    with pytest.raises(RuntimeError, match="intentionally not recreated"):
        _migration().downgrade()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_retirement_against_isolated_postgresql_schema(database):
    source, tables = database
    url = _get_async_url(settings.agent_hub_db_url)
    assert make_url(url).database == "agent_hub_test"
    engine = create_async_engine(url)
    schema = "neri_model_retirement_" + uuid4().hex
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
                before = sync.execute(sa.select(tables["agent_benchmark_runs"]).where(tables["agent_benchmark_runs"].c.id == "generic")).first()
                _apply(sync)
                _apply(sync)
                inspector = sa.inspect(sync)
                assert not inspector.has_table("typesafe_jev_dispatches")
                assert not inspector.has_table("typesafe_jev_budgets")
                assert sync.execute(sa.select(tables["agent_benchmark_runs"])).first() == before
                assert sync.execute(sa.text("SELECT * FROM agent_benchmark_attempts")).all() == [("generic-attempt", "generic", "generic evidence")]
                assert {column["name"] for column in inspector.get_columns("agent_benchmark_attempts")} == {"id", "benchmark_run_id", "raw_content"}

            await connection.run_sync(exercise)
            await connection.rollback()
    finally:
        await engine.dispose()
