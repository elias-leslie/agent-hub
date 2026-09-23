"""Purge the reviewed obsolete March 2026 one-time Persona follow-ups.

Revision ID: 6d7e8f9a0b1c
Revises: 5c6b7a8d9e0f

This intentionally discards the 52 profiles, their Persona schedule rows, and
profile revisions. No historical records or downgrade restoration are retained.
"""

from datetime import UTC, datetime
from uuid import UUID

import sqlalchemy as sa

from alembic import op

revision = "6d7e8f9a0b1c"
down_revision = "5c6b7a8d9e0f"
branch_labels = None
depends_on = None

# Exact pairs reviewed on 2026-09-23. The four never-run reminders are included.
EXPECTED_PAIRS = (
    ('04e352a1-99b0-4690-a09c-692853468f36', '48a4046a-31f2-4380-aa81-f102b838118a'),
    ('0d2165ea-3d52-44e6-bf0a-b8a980c1a62a', '35691a4f-e8f8-41fd-814b-e331ee0aa389'),
    ('0e983c40-e719-401e-b88e-bd88a01efc06', 'a126a95c-629e-4da3-8577-c3d89c82e1e0'),
    ('0f442c8d-fca5-4ee5-b1d2-b2d7bae91da4', 'e8837f2d-ae08-4d2d-8e51-c8201f442ebe'),
    ('1d6400b3-da95-441b-a10d-8280b7a9c643', 'ff648e41-e297-489c-bfc4-9d6b76b20a7c'),
    ('26543504-4139-4a43-952e-12e346cf3538', '145e50b2-c019-4a2e-99b2-a596f9442116'),
    ('4683321a-a7a3-4ff5-933b-396c3071edb2', '5d9bdebd-6b05-4c1f-a5d3-6fdfaba5e23c'),
    ('47f3d956-d238-4047-b5f5-fb913862e992', '61e4e33f-65c6-42d9-ae14-25ddbef55288'),
    ('4fb753a3-71d4-43e1-9783-11c5fae1621f', 'b184e7da-49db-4ebe-8495-57d1042469e1'),
    ('50235ea1-f1ab-4b3d-9d37-7a693388627c', '5d097e93-cb4e-46c1-8738-f018610a8235'),
    ('5598ec70-a3ae-4de3-b679-578de74feffc', '430db4a6-a7d4-494f-b1a5-e22bc07fd031'),
    ('5817ac8c-8a42-4077-b27a-5ec95d57e9d0', '1abb3278-a93b-46cb-945a-709bd90beb1e'),
    ('646f5909-502e-41f2-a3d2-14ea10fd7679', 'fd1cc6bf-40b8-4a79-9d12-263513bf368a'),
    ('6488c76a-9f8e-43b0-9fec-5e407d9d323e', 'b8dd6fae-2658-4c35-ad29-1753bd909e42'),
    ('6b46d309-edc7-4ae4-b8a5-a2dd22812b8f', '0c3f934f-816f-4dc0-8571-2f467d57e5a1'),
    ('6b70b764-cbd7-4920-b8a8-86bdf0124eb0', 'ebec4fd0-bba3-4c64-8351-d462083fafb4'),
    ('781c3d31-18d8-49f4-a36f-d68c019105be', '226024ab-a2cd-4101-b1c6-4eb175c60ea7'),
    ('78cf1de9-2a40-48dc-a8ba-5b640c49c80b', 'b5fc47e8-7ca6-4b60-9731-5fba08c07dd4'),
    ('799fbc64-a9f5-472c-9e75-5b3bb2e2dc81', '61bd8d08-998b-4350-997a-62b62cb2d335'),
    ('7c8b7b37-332b-4e22-89ff-f0e545623b4b', '1741a31e-82dc-467a-8f7f-b6a766b0e4bd'),
    ('7ce5530d-b4f4-48b7-a597-3163e302f954', '34d70ccf-ce38-467e-aa79-0310f73e9a7f'),
    ('7d2129f1-9578-43f1-a5bd-5b561cfa5b03', '6ea21543-ab1e-4f64-aaa3-26d05fa0a98f'),
    ('82adf0a6-c68a-4aa2-9366-74ff8a468277', '5ccc5317-baee-418e-8367-2870b4e3e75a'),
    ('83653747-030e-4a3c-a7de-1a5d3c0ce944', '44acf65c-1ba2-4049-89a6-9462bbe5015a'),
    ('864c390b-cd05-4959-87e3-193d360a0018', 'd2a84d58-29ca-448c-b6db-dadc48b38137'),
    ('8ad57ca6-6f01-4cb3-acea-3819e6b94c32', 'd9a23e14-6924-45c6-b701-0076b91125df'),
    ('91c921de-093a-48e7-9627-4749f93ae5d3', 'de39e393-186e-4fdd-9630-eecc8ea42521'),
    ('93c5463a-0353-4614-afb1-aa0c911dc691', '4caf4c74-84aa-4a3b-878c-283679265d8a'),
    ('9f946f6e-2b71-4584-87f6-baf00ba1b17f', '670917ef-701a-4b89-8dcc-b8ed90cfa01c'),
    ('a66d0f72-b034-4e80-844f-c9c33ed5440e', '7f2f00b5-dea4-4742-a735-63d607ae836f'),
    ('a8286253-930f-4f6b-b96c-6c28a60ffdac', '14eec8ee-452e-4a31-8657-e9fe7135bd38'),
    ('a8643d43-7e91-484b-8cb5-9e4cbc2ef94d', '0bc232a6-7845-4548-97fd-62a3ca19f97b'),
    ('a8d372a5-5ff0-43c3-8a23-2ee2afe690a9', '3019494f-247e-40ce-bf5d-aeefaf7ba13e'),
    ('b1811453-2dbd-4d01-94c4-f1647b507354', '0c60eb9f-d1f0-4d12-8db1-daa4115783ef'),
    ('c0132292-2ec5-43ee-9b03-a5843b5f00d9', '0389b896-cdc4-44c6-9798-77654bac7377'),
    ('c3a6a05c-5066-4aac-b94d-4cb5e7995428', 'ecd3f4f5-230b-4850-b725-f41bcf4a3b2f'),
    ('c9a0b233-4b55-438c-b971-8c42faafac1a', '88e76d27-66f8-4953-a78c-cf93091cebc0'),
    ('ca355193-dd52-449e-839c-6f64174fb28f', '4e94805e-b8b2-4d3e-8038-f85bf036a397'),
    ('cc7add09-aff9-4e11-853a-5386538df884', '1e9c728b-b30d-4ca8-b9ae-fa0c4a37cc22'),
    ('cd3b9b90-83c8-41ed-ae1e-614ca6fa962f', 'df4af94b-6831-43be-b70e-5d4c1b338d95'),
    ('d112093c-eaa3-413b-817f-fda75e4cbd2e', '2d3844a0-b98a-438b-a0a2-a52360387d25'),
    ('d2eeb59a-d30f-4990-8ab6-5c84c3bd7868', 'eb388cff-0a9c-4e45-80a0-8a2b2a865da0'),
    ('d77b8470-5f98-4afb-8ff1-d9a8456df654', '1ee028bf-a4a0-4c87-82d4-9ce5ae311841'),
    ('d852be3e-54c5-4cdc-88b4-78da6f6a8715', 'c0324d76-105e-4b3e-a64b-331cf336ded8'),
    ('e3ff824b-367a-4d5f-acfc-184d8070fa82', 'b27739c2-686a-439a-8432-52e9c5214e50'),
    ('e8cebf78-e347-4705-a5cf-6fda75d3eb5f', 'b3e11288-549a-429a-bc86-fc7848318150'),
    ('ea43ea87-46f7-4bc3-b371-995a2ac43c7c', '32ad7ac0-2455-4d7d-b285-24b133c282b8'),
    ('eb7e8829-506d-4b72-b900-dae8865d52ed', '0fa92b42-75ad-404d-8867-dd95f28cacab'),
    ('ed4e42a2-4c18-45bd-be2c-6acd3596e6ec', '3203f02e-3bdc-404c-8097-101dbfbe72f9'),
    ('f115e158-09f1-494c-a7b8-19b9cdeefdec', '979484b1-7991-40d6-aca6-afdc835cf95e'),
    ('f490214a-69eb-4991-ac7d-48ec4ab21e4c', '8e8cefc8-295c-4035-be39-85dc5fb169d5'),
    ('f950f5c4-b861-49c0-bebb-daa2686791df', 'fed200bb-c738-441d-bf98-b1138209d3c2'),
)
_START = datetime(2026, 3, 1, tzinfo=UTC)
_END = datetime(2026, 4, 1, tzinfo=UTC)


def _select_rows(bind, table: str, columns: str, ids: tuple[str | UUID, ...]):
    query = sa.text(f"SELECT {columns} FROM {table} WHERE id IN :ids").bindparams(
        sa.bindparam("ids", expanding=True)
    )
    return {str(row["id"]): row for row in bind.execute(query, {"ids": ids}).mappings()}


def upgrade() -> None:
    bind = op.get_bind()
    # Wait for in-flight imports, then prevent new imports/writes until commit.
    bind.execute(sa.text(
        "LOCK TABLE automation_profiles, persona_scheduled_jobs IN ACCESS EXCLUSIVE MODE"
    ))
    bind.execute(sa.text(
        "LOCK TABLE automation_runs, automation_profile_revisions IN SHARE ROW EXCLUSIVE MODE"
    ))
    profile_ids = tuple(profile_id for profile_id, _ in EXPECTED_PAIRS)
    owner_ids = tuple(UUID(owner_id) for _, owner_id in EXPECTED_PAIRS)
    profiles = _select_rows(bind, "automation_profiles", "*", profile_ids)
    owners = _select_rows(bind, "persona_scheduled_jobs", "*", owner_ids)
    if not profiles and not owners:
        return  # Fresh databases never contained this historical set.
    if set(profiles) != set(profile_ids) or set(owners) != {str(owner_id) for owner_id in owner_ids}:
        raise RuntimeError("Reviewed Persona cleanup set is incomplete; no rows deleted")

    run_counts = {0: 0, 1: 0}
    for profile_id, owner_id in EXPECTED_PAIRS:
        profile = profiles[profile_id]
        owner = owners[owner_id]
        if not (
            profile["project_id"] == "agent-hub"
            and profile["workflow_key"] == "agent-hub.persona_job"
            and profile["subject_id"] == f"persona:{owner['persona_id']}"
            and profile["source_ref"] == f"persona:{owner_id}"
            and profile["schedule_type"] == owner["schedule_type"] == "at"
            and profile["schedule_value"] == owner["schedule_value"]
            and profile["enabled"] is False
            and owner["enabled"] is False
            and profile["clock_owner"] == "central"
            and profile["max_runs"] == owner["max_runs"] == 1
            and profile["run_count"] == owner["run_count"]
            and profile["run_count"] in run_counts
            and profile["revision"] == 2
            and profile["imported_unreviewed_count"] == 0
        ):
            raise RuntimeError("Reviewed Persona cleanup state changed; no rows deleted")
        scheduled_for = datetime.fromisoformat(profile["schedule_value"].replace("Z", "+00:00"))
        if scheduled_for.tzinfo is None or not _START <= scheduled_for.astimezone(UTC) < _END:
            raise RuntimeError("Reviewed Persona schedule changed; no rows deleted")
        if any(
            stamp is not None and stamp.astimezone(UTC) >= _END
            for stamp in (profile["last_run_at"], owner["last_run_at"])
        ):
            raise RuntimeError("Reviewed Persona job has recent activity; no rows deleted")
        run_counts[profile["run_count"]] += 1
    if run_counts != {0: 4, 1: 48}:
        raise RuntimeError("Reviewed Persona run-count split changed; no rows deleted")

    runs = bind.execute(sa.text(
        "SELECT count(*) FROM automation_runs WHERE profile_id IN :ids"
    ).bindparams(sa.bindparam("ids", expanding=True)), {"ids": profile_ids}).scalar_one()
    revisions = bind.execute(sa.text(
        "SELECT count(*) FROM automation_profile_revisions WHERE profile_id IN :ids"
    ).bindparams(sa.bindparam("ids", expanding=True)), {"ids": profile_ids}).scalar_one()
    if runs != 0 or revisions != 104:
        raise RuntimeError("Reviewed Persona receipts/revisions changed; no rows deleted")

    delete = sa.text("DELETE FROM persona_scheduled_jobs WHERE id IN :ids").bindparams(
        sa.bindparam("ids", expanding=True)
    )
    if bind.execute(delete, {"ids": owner_ids}).rowcount != 52:
        raise RuntimeError("Persona owner deletion was incomplete")
    delete = sa.text("DELETE FROM automation_profiles WHERE id IN :ids").bindparams(
        sa.bindparam("ids", expanding=True)
    )
    if bind.execute(delete, {"ids": profile_ids}).rowcount != 52:
        raise RuntimeError("Automation profile deletion was incomplete")


def downgrade() -> None:
    # Deleted one-time reminders and their content are intentionally irrecoverable.
    pass
