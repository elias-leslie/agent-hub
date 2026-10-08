"""Remove exact Neri model experiment storage and catalog identity.

Revision ID: 5b9e4c2a7d10
Revises: h3f4e5d6c7b8
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "5b9e4c2a7d10"
down_revision: str | Sequence[str] | None = "h3f4e5d6c7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MODEL_ID = "local/qwen3.8-27b-gsq-rco-iq3_s-mtp"
_MODEL_NAME = "Qwen3.8 27B GSQ/RCO IQ3_S (Neri candidate)"
_PILOT_ID = "neri-jev-pilot-2026-09"
_TABLES = ("typesafe_jev_dispatches", "typesafe_jev_budgets")
_ATTEMPT_FIELDS = (
    "task_family", "harness_arm", "dimension_scores", "runtime_metrics",
    "safety_failures", "oracle_details", "artifact_identity", "input_sha256", "prompt_revision",
)
_RUN_KINDS = {"neri_local_worker_evaluation", "neri_local_study_preflight"}
_BENCHMARK_TYPES = {"neri_local_worker", "neri_local_worker_study"}


def _retired_benchmarks(bind, inspector) -> tuple[sa.Table | None, sa.Table | None, list[str]]:
    runs = attempts = None
    retired_ids = []
    if inspector.has_table("agent_benchmark_runs"):
        runs = sa.Table("agent_benchmark_runs", sa.MetaData(), autoload_with=bind)
        identity = [runs.c[name] for name in ("id", "agent_slug", "project_id", "suite_id", "run_kind", "models", "metadata")]
        for row in bind.execute(sa.select(*identity)).mappings():
            metadata = row["metadata"] or {}
            benchmark_type = metadata.get("benchmark_type")
            if row["agent_slug"] != "neri-local-candidate" and row["run_kind"] not in _RUN_KINDS and benchmark_type not in _BENCHMARK_TYPES:
                continue
            if (
                row["agent_slug"] != "neri-local-candidate"
                or row["project_id"] != "security-research"
                or row["run_kind"] not in _RUN_KINDS
                or benchmark_type not in _BENCHMARK_TYPES
                or row["models"] != [_MODEL_ID]
                or not row["suite_id"].startswith(("neri-local-worker-", "neri-local-study-"))
            ):
                raise RuntimeError("Neri benchmark identity changed; cleanup stopped")
            retired_ids.append(row["id"])
    if inspector.has_table("agent_benchmark_attempts"):
        attempts = sa.Table("agent_benchmark_attempts", sa.MetaData(), autoload_with=bind)
        fields = [attempts.c[name] for name in _ATTEMPT_FIELDS if name in attempts.c]
        if fields:
            statement = sa.select(*fields)
            if retired_ids:
                statement = statement.where(attempts.c.benchmark_run_id.not_in(retired_ids))
            for row in bind.execute(statement):
                if any(value not in (None, {}, [], "", "{}", "[]") for value in row):
                    raise RuntimeError("Unrelated benchmark uses Neri experiment columns; cleanup stopped")
    return runs, attempts, retired_ids


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    present = {name for name in (*_TABLES, "models", "model_aliases", "agents") if inspector.has_table(name)}

    # These tables were created only for the Neri pilot. Fail before any deletion
    # if another workflow has reused them or a catalog identity has been changed.
    for table, column in (("typesafe_jev_budgets", "key"), ("typesafe_jev_dispatches", "budget_key")):
        if table in present:
            unexpected = bind.execute(
                sa.text(f"SELECT {column} FROM {table} WHERE {column} != :key OR {column} IS NULL"),
                {"key": _PILOT_ID},
            ).first()
            if unexpected:
                raise RuntimeError(f"Neri experiment table contains unrelated data: {table}")

    if "models" in present:
        model = bind.execute(
            sa.text("SELECT name, alias, provider, source FROM models WHERE id = :id"),
            {"id": _MODEL_ID},
        ).first()
        if model and tuple(model) != (_MODEL_NAME, "local/neri-qwen", "local", "seed"):
            raise RuntimeError("Neri experiment model identity changed; cleanup stopped")

    if "agents" in present:
        agents = sa.Table("agents", sa.MetaData(), autoload_with=bind)
        columns = [agents.c[name] for name in ("primary_model_id", "fallback_models", "escalation_model_id") if name in agents.c]
        if columns:
            for values in bind.execute(sa.select(*columns)):
                for value in values:
                    if value == _MODEL_ID or (isinstance(value, list) and _MODEL_ID in value):
                        raise RuntimeError("An agent still references the Neri experiment model; cleanup stopped")

    runs, attempts, retired_ids = _retired_benchmarks(bind, inspector)

    if retired_ids:
        if attempts is not None:
            bind.execute(attempts.delete().where(attempts.c.benchmark_run_id.in_(retired_ids)))
        assert runs is not None
        bind.execute(runs.delete().where(runs.c.id.in_(retired_ids)))
    if attempts is not None:
        for index in inspector.get_indexes("agent_benchmark_attempts"):
            if index["name"] in {
                "ix_agent_benchmark_attempts_task_family", "ix_agent_benchmark_attempts_harness_arm",
            }:
                op.drop_index(index["name"], table_name="agent_benchmark_attempts")
        for name in _ATTEMPT_FIELDS:
            if name in attempts.c:
                op.drop_column("agent_benchmark_attempts", name)

    # Do not use CASCADE: unexpected inbound references must stop the migration.
    for table in _TABLES:
        if table in present:
            op.drop_table(table)
    if "model_aliases" in present:
        bind.execute(sa.text("DELETE FROM model_aliases WHERE model_id = :id"), {"id": _MODEL_ID})
    if "models" in present:
        bind.execute(sa.text("DELETE FROM models WHERE id = :id"), {"id": _MODEL_ID})


def downgrade() -> None:
    raise RuntimeError(
        "Neri model experiments are intentionally not recreated; "
        "restore the pre-cleanup Agent Hub snapshot if rollback is required."
    )
