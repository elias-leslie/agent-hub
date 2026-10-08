"""Retire the exact Neri notification-only definition and profile.

Revision ID: 7e31a9c4f602
Revises: 5b9e4c2a7d10
"""

import sqlalchemy as sa

from alembic import op

revision = "7e31a9c4f602"
down_revision = "5b9e4c2a7d10"
branch_labels = None
depends_on = None

_WORKFLOW = "neri/notification_maintenance"
_PROFILE_ID = "1b94e5ba-f7fa-4635-9f94-9bcc3ec34c31"


def upgrade() -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    names = (
        "automation_definitions", "automation_profiles",
        "automation_profile_revisions", "automation_runs",
    )
    tables = {
        name: sa.Table(name, metadata, autoload_with=bind)
        for name in names if sa.inspect(bind).has_table(name)
    }
    # Fence concurrent clock/import writes for the guard-and-delete transaction.
    if tables and bind.dialect.name == "postgresql":
        bind.exec_driver_sql(
            "LOCK TABLE " + ", ".join(f'"{name}"' for name in tables)
            + " IN SHARE ROW EXCLUSIVE MODE"
        )

    definitions = tables.get("automation_definitions")
    if definitions is not None:
        for row in bind.execute(sa.select(definitions).where(
            definitions.c.workflow_key == _WORKFLOW
        )).mappings():
            if (
                row["version"] != 1 or row["owner_project_id"] != "neri"
                or row["dispatch_kind"] != "callback"
                or row["dispatch_target"] != "/automations/dispatch/notification_maintenance"
            ):
                raise RuntimeError("Neri notification definition identity/revision changed")

    profiles = tables.get("automation_profiles")
    if profiles is not None:
        for row in bind.execute(sa.select(profiles).where(sa.or_(
            profiles.c.id == _PROFILE_ID, profiles.c.workflow_key == _WORKFLOW,
        ))).mappings():
            if (
                row["id"] != _PROFILE_ID or row["project_id"] != "neri"
                or row["workflow_key"] != _WORKFLOW or row["definition_version"] != 1
                or row["subject_id"] is not None
            ):
                raise RuntimeError("Neri notification profile identity changed or extra profile exists")

    revisions = tables.get("automation_profile_revisions")
    if revisions is not None:
        for row in bind.execute(sa.select(revisions).where(
            revisions.c.profile_id == _PROFILE_ID
        )).mappings():
            snapshot = row["snapshot"]
            if (
                not isinstance(snapshot, dict) or snapshot.get("project_id") != "neri"
                or snapshot.get("workflow_key") != _WORKFLOW
                or snapshot.get("definition_version") != 1
                or snapshot.get("subject_id") is not None
            ):
                raise RuntimeError("Neri notification revision identity changed")

    runs = tables.get("automation_runs")
    if runs is not None:
        for row in bind.execute(sa.select(runs).where(sa.or_(
            runs.c.profile_id == _PROFILE_ID, runs.c.workflow_key == _WORKFLOW,
        ))).mappings():
            if (
                row["profile_id"] != _PROFILE_ID or row["project_id"] != "neri"
                or row["workflow_key"] != _WORKFLOW or row["definition_version"] != 1
            ):
                raise RuntimeError("Neri notification run identity changed")
            if row["status"] != "succeeded":
                raise RuntimeError("Neri notification run is not a known succeeded terminal receipt")

    # Only this profile's terminal children are retired. Receipt shape does not
    # establish a delivery count; older receipts omit that fact entirely.
    if runs is not None:
        bind.execute(runs.delete().where(runs.c.profile_id == _PROFILE_ID))
    if revisions is not None:
        bind.execute(revisions.delete().where(revisions.c.profile_id == _PROFILE_ID))
    if profiles is not None:
        bind.execute(profiles.delete().where(profiles.c.id == _PROFILE_ID))
    if definitions is not None:
        bind.execute(definitions.delete().where(definitions.c.workflow_key == _WORKFLOW))


def downgrade() -> None:
    raise RuntimeError(
        "The retired Neri notification product is intentionally not recreated; "
        "restore the pre-cleanup snapshot if rollback is required"
    )
