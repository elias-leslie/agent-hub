"""Retire SummitFlow work pickup and task generation automations.

Revision ID: e2a8c4f6b1d3
Revises: d1f7b3a5c9e2

SummitFlow retired its autonomous pipeline; dispatches for these keys now
return workflow_retired. Deletes the summitflow/work_pickup and
summitflow/task_generation definitions, their profiles (revisions cascade) and
runs, and strips the autonomous_*, quality_gate_* and routine_upkeep_enabled
keys from stored project policies and definition policy schemas.
summitflow/browser_workflow stays. The rows were archived with pg_dump to
backups/2026-10-11-sf-autonomous-retirement before this ran. Upgrade is
idempotent; downgrade is a no-op (restore from that archive if ever needed).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "e2a8c4f6b1d3"
down_revision: str | Sequence[str] | None = "d1f7b3a5c9e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KEYS = "('summitflow/work_pickup', 'summitflow/task_generation')"
_RETIRED_KEY = "(k LIKE 'autonomous\\_%' OR k LIKE 'quality\\_gate\\_%' OR k = 'routine_upkeep_enabled')"


def upgrade() -> None:
    op.execute(f"DELETE FROM public.automation_runs WHERE workflow_key IN {_KEYS}")
    op.execute(f"DELETE FROM public.automation_profiles WHERE workflow_key IN {_KEYS}")
    op.execute(f"DELETE FROM public.automation_definitions WHERE workflow_key IN {_KEYS}")
    op.execute(
        f"""
        UPDATE public.automation_project_policies p
        SET config = (
            SELECT coalesce(jsonb_object_agg(k, v), '{{}}'::jsonb)
            FROM jsonb_each(p.config::jsonb) AS e(k, v)
            WHERE NOT {_RETIRED_KEY}
        )::json,
            revision = p.revision + 1
        WHERE EXISTS (SELECT 1 FROM json_object_keys(p.config) AS k WHERE {_RETIRED_KEY})
        """
    )
    op.execute(
        f"""
        UPDATE public.automation_definitions d
        SET policy_schema = jsonb_set(
            d.policy_schema::jsonb, '{{properties}}',
            (
                SELECT coalesce(jsonb_object_agg(k, v), '{{}}'::jsonb)
                FROM jsonb_each(d.policy_schema::jsonb -> 'properties') AS e(k, v)
                WHERE NOT {_RETIRED_KEY}
            )
        )::json
        WHERE EXISTS (
            SELECT 1 FROM json_object_keys(d.policy_schema -> 'properties') AS k WHERE {_RETIRED_KEY}
        )
        """
    )


def downgrade() -> None:
    pass
