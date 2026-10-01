"""Exercise the public feedback interface against isolated PostgreSQL temp tables."""

import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.schema import CreateTable

from app.api.feedback import create_feedback, get_feedback_item, vote_on_feedback
from app.api.schemas.feedback import FeedbackItemCreate, FeedbackVoteCreate
from app.models.feedback import FeedbackItem, FeedbackVote
from app.services import feedback_storage

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def occurrence_db():
    configured = os.environ.get("TEST_AGENT_HUB_DB_URL")
    if not configured:
        pytest.skip("TEST_AGENT_HUB_DB_URL is required")
    url = make_url(configured).set(drivername="postgresql+asyncpg")
    assert url.database and url.database.endswith("_test"), "Feedback tests require a test database"
    engine = create_async_engine(url)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        await connection.execute(text("CREATE TEMP TABLE sessions (id varchar(36) PRIMARY KEY)"))
        for model in (FeedbackItem, FeedbackVote):
            ddl = str(CreateTable(model.__table__).compile(dialect=connection.dialect))
            await connection.execute(text(ddl.replace("CREATE TABLE", "CREATE TEMP TABLE", 1)))
        await connection.execute(text("""
            ALTER TABLE feedback_items ADD COLUMN search_vector tsvector
            GENERATED ALWAYS AS (to_tsvector('english', coalesce(title, '') || ' ' || coalesce(description, ''))) STORED
        """))
        async with AsyncSession(bind=connection, expire_on_commit=False,
                                join_transaction_mode="create_savepoint") as session:
            yield session
        await transaction.rollback()
    await engine.dispose()


def report(identity: str, *, title: str = "Native feedback recurrence", project: str = "project-a", **fields):
    return FeedbackItemCreate(component_id="xc.product", feedback_type="friction", title=title,
                              project_id=project, occurrence_id=identity, **fields)


async def test_two_sessionless_reports_and_relay(occurrence_db):
    db = occurrence_db
    first = await create_feedback(report("origin-a", run_ref="run-a", role="hunter"), db)
    second = await create_feedback(report("origin-b", project="project-b", run_ref="run-b", role="reporter",
                                         consequence="Report assembly delayed", evidence_refs=["sanitized:artifact-b"]), db)
    assert first.created and not second.created and second.voted
    assert first.item.id == second.item.id
    assert second.item.occurrence_count == 2
    assert second.item.independent_run_count == 2
    assert second.item.affected_projects == ["project-a", "project-b"]
    assert second.item.affected_roles == ["hunter", "reporter"]
    timestamp = second.item.updated_at
    relay = await create_feedback(report("origin-b", role="orchestrator", consequence="A relay must change nothing"), db)
    assert not relay.created and not relay.voted
    assert relay.item.occurrence_count == 2 and relay.item.updated_at == timestamp
    detail = await get_feedback_item(second.item.id, db)
    assert len(detail.occurrences) == 2
    assert {item.occurrence_id for item in detail.occurrences} == {"origin-a", "origin-b"}
    occurrence = next(item for item in detail.occurrences if item.occurrence_id == "origin-b")
    assert occurrence.consequence == "Report assembly delayed"
    assert occurrence.role == "reporter"
    assert occurrence.evidence_refs == ["sanitized:artifact-b"]
    assert await feedback_storage.count_feedback_items(db, project_id="project-b") == 1
    assert (await feedback_storage.search_feedback_items(db, project_id="project-b"))[0].id == first.item.id


async def test_initial_report_and_legacy_session_vote_count_once(occurrence_db):
    db = occurrence_db
    session_id = str(uuid4())
    await db.execute(text("INSERT INTO sessions (id) VALUES (:id)"), {"id": session_id})
    created = await create_feedback(report("initial", session_id=session_id), db)
    assert created.item.occurrence_count == 1
    repeated = await vote_on_feedback(created.item.id, FeedbackVoteCreate(session_id=session_id), db)
    assert isinstance(repeated, dict) and repeated["message"] == "Already voted"
    assert (await get_feedback_item(created.item.id, db)).occurrence_count == 1
    await db.execute(text("DELETE FROM sessions WHERE id = :id"), {"id": session_id})
    await db.commit()
    db.expire_all()
    detail = await get_feedback_item(created.item.id, db)
    assert detail.created_by_session_id is None
    assert detail.occurrences[0].session_id is None
    assert detail.occurrences[0].occurrence_id == "initial"
    assert detail.occurrence_count == 1


async def test_merge_preserves_every_occurrence_and_old_references(occurrence_db):
    db = occurrence_db
    first = await create_feedback(report("canonical", title="Canonical feedback"), db)
    second = await create_feedback(report("duplicate", title="Duplicate feedback", project="project-b"), db)
    await feedback_storage.merge_feedback_items(db, source_item_id=second.item.id, target_item_id=first.item.id)
    await db.commit()
    db.expire_all()
    detail = await get_feedback_item(second.item.id, db)
    assert detail.id == first.item.id and detail.occurrence_count == 2
    assert {item.occurrence_id for item in detail.occurrences} == {"canonical", "duplicate"}
    repeated = await create_feedback(report("duplicate", title="Duplicate feedback"), db)
    assert repeated.item.id == first.item.id and repeated.item.occurrence_count == 2
    assert await feedback_storage.count_feedback_items(db) == 1
    assert await feedback_storage.count_feedback_items(db, project_id="project-b") == 1
    # A writer whose pre-merge item resolution is stale must follow the redirect.
    late = await feedback_storage.vote_on_item(db, item_id=second.item.id, occurrence_id="late-writer")
    assert late is not None and late.feedback_item_id == first.item.id
    assert (await get_feedback_item(first.item.id, db)).occurrence_count == 3


async def test_fresh_recurrence_on_old_item_is_in_summary_and_retained(occurrence_db):
    db = occurrence_db
    old = datetime.now(UTC) - timedelta(days=200)
    first = await create_feedback(report("old", occurred_at=old), db)
    await db.execute(text("UPDATE feedback_items SET created_at = :old WHERE id = :id"), {"old": old, "id": first.item.id})
    second = await create_feedback(report("new", run_ref="new-run"), db)
    assert second.item.occurrence_count == 2
    summary = await feedback_storage.get_feedback_summary(db, days=7)
    assert summary["top_unresolved"][0]["id"] == UUID(first.item.id)
    assert summary["top_unresolved"][0]["occurrence_count"] == 2
    await feedback_storage.update_feedback_status(db, first.item.id, status="archived")
    await db.execute(text("UPDATE feedback_items SET updated_at = :old WHERE id = :id"), {"old": old, "id": first.item.id})
    assert await feedback_storage.purge_old_archived_feedback_items(db, older_than_days=90) == 0


async def test_explicit_link_and_acknowledgement_only_update_feedback(occurrence_db):
    db = occurrence_db
    first = await create_feedback(report("passive"), db)
    item = await feedback_storage.update_feedback_status(db, first.item.id, status="acknowledged", linked_task_id="task-explicit")
    assert item is not None
    assert item.status == "acknowledged" and item.linked_task_id == "task-explicit"
    assert item.occurrence_count == 1
    # The isolated schema has no task table or task service. Capture, vote, merge,
    # acknowledgement and linking therefore exercise no task creation interface.


async def test_legacy_backfill_keeps_only_attributable_occurrences(occurrence_db):
    from importlib.util import module_from_spec, spec_from_file_location
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    db = occurrence_db
    connection = await db.connection()
    for name in ("occurrence_id", "source_project_id", "run_ref", "role", "occurred_at",
                 "consequence", "workaround", "evidence_refs", "source_kind"):
        await db.execute(text(f"ALTER TABLE feedback_votes DROP COLUMN {name}"))
    for name in ("last_seen_at", "independent_run_count", "affected_roles", "affected_projects", "merged_into_id"):
        await db.execute(text(f"ALTER TABLE feedback_items DROP COLUMN {name}"))
    await db.execute(text("ALTER TABLE feedback_votes ADD CONSTRAINT uq_feedback_votes_item_session UNIQUE (feedback_item_id, session_id)"))
    await db.execute(text("ALTER TABLE feedback_votes ALTER COLUMN session_id SET NOT NULL"))
    await db.execute(text("ALTER TABLE feedback_votes DROP CONSTRAINT fk_feedback_votes_sessions_session_id"))
    await db.execute(text("ALTER TABLE feedback_votes ADD CONSTRAINT feedback_votes_session_id_fkey FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE"))
    item_id = str(uuid4())
    session_id = str(uuid4())
    await db.execute(text("INSERT INTO sessions (id) VALUES (:id)"), {"id": session_id})
    await db.execute(text("""INSERT INTO feedback_items (id, component_id, feedback_type, title, project_id, vote_count)
                            VALUES (:id, 'xc.product', 'friction', 'Legacy report', 'project-a', 99)"""), {"id": item_id})
    await db.execute(text("INSERT INTO feedback_votes (feedback_item_id, session_id, comment) VALUES (:id, :session_id, 'Retained vote')"), {"id": item_id, "session_id": session_id})
    migration_path = Path(__file__).parents[2] / "alembic/versions/f1e2d3c4b5a6_feedback_occurrences.py"
    spec = spec_from_file_location("feedback_occurrences_migration", migration_path)
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)

    def upgrade(sync_connection):
        migration.__dict__["op"] = Operations(MigrationContext.configure(sync_connection))
        migration.upgrade()

    await connection.run_sync(upgrade)
    retained = (await db.execute(text("SELECT occurrence_id, run_ref, role, source_kind FROM feedback_votes ORDER BY source_kind"))).mappings().all()
    assert len(retained) == 2  # One retained initial report and one retained vote, not 99 invented reports.
    assert {row["source_kind"] for row in retained} == {"legacy_report", "legacy_vote"}
    assert all(row["run_ref"] is None and row["role"] is None for row in retained)
    item = await feedback_storage.get_feedback_item(db, item_id)
    assert item is not None
    assert item.occurrence_count == 2 and item.independent_run_count == 0
    await db.execute(text("DELETE FROM sessions WHERE id = :id"), {"id": session_id})
    retained_sessions = (await db.execute(text("SELECT session_id FROM feedback_votes"))).scalars().all()
    assert len(retained_sessions) == 2 and all(value is None for value in retained_sessions)
