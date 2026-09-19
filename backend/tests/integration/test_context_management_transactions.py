"""Real PostgreSQL rollback, atomic save, revision and undo verification.

Only agent_hub_test is accepted. Fixture schema and data live in an
outer transaction that is always rolled back; existing test data is preserved.
"""
from __future__ import annotations

import uuid

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import _get_engine
from app.models import Base
from app.models.context_governance import ContextRecord
from app.models.memory_unified import Memory
from app.models.prompt import Prompt
from app.services.context_governance import (
    ContextDraft,
    PlacementEdit,
    SourceEdit,
    apply_draft,
    get_source,
    inventory,
    preview_draft,
    undo_change,
)
from app.services.context_policy import ContextPolicy, source_revision
from app.services.runtime_context import CanonicalContextDeliveryRequest


def apply_test_migrations(connection):
    # The shared test database has a partial metadata-built schema and no
    # Alembic baseline. Build an isolated transactional schema, preserving it.
    schema = "context_test_" + uuid.uuid4().hex
    with Operations.context(MigrationContext.configure(connection)):
        from alembic import op
        op.execute(f'CREATE SCHEMA "{schema}"')
        op.execute(f'SET LOCAL search_path TO "{schema}", public')
        for table in Base.metadata.sorted_tables:
            op.create_table(table.name, *(column._copy() for column in table.columns))


@pytest.mark.integration
@pytest.mark.asyncio
async def test_atomic_preview_save_stale_undo_and_memory_identity():
    async with _get_engine().connect() as connection:
        assert (await connection.execute(text('SELECT current_database()'))).scalar() == 'agent_hub_test'
        try:
            await connection.run_sync(apply_test_migrations)
            async with AsyncSession(bind=connection, expire_on_commit=False, join_transaction_mode='create_savepoint') as db:
                suffix = uuid.uuid4().hex[:8]
                row = Prompt(slug=f'context-test-{suffix}', name='Context transaction fixture', content='Original fixture guidance.', enabled=True, is_global=True, prompt_type='standard', exclude_agents=[], context_policy=ContextPolicy(scope='global').model_dump())
                memory = Memory(content='Persistent memory identity fixture.', name='Identity fixture', memory_type='reference', scope='global', tier=3, status='active', loaded_count=7, metadata_={})
                scoped = Prompt(slug=f'scoped-test-{suffix}', name='Scoped export fixture', content='Scoped instructions.', enabled=True, is_global=False, prompt_type='standard', exclude_agents=[], context_policy=ContextPolicy(scope='project', targets=['security-research']).model_dump())
                db.add_all([row, scoped, memory])
                await db.flush()
                from scripts.export_seeds import export_seeds
                exported = await export_seeds(db)
                assert any(p['slug'] == scoped.slug and p['context_policy']['targets'] == ['security-research'] for p in exported['prompts'])
                prompt_id, memory_id = row.slug, str(memory.id)
                context = CanonicalContextDeliveryRequest(consumer_surface='codex', include_memories=False, include_project_index=False, include_tool_capabilities=False, include_continuity=False)
                baseline = await inventory(db, context)
                revision = source_revision(row)
                draft = ContextDraft(context=context, edits=[SourceEdit(source_type='prompt', source_id=prompt_id, expected_revision=revision, content='Updated fixture guidance.')])
                preview = await preview_draft(db, draft)
                assert 'Updated fixture guidance.' in preview['delivery']['rendered']
                assert (await get_source(db, 'prompt', prompt_id)).content == 'Original fixture guidance.'
                assert not list((await db.execute(select(ContextRecord).where(ContextRecord.kind == 'change'))).scalars())
                saved = await apply_draft(db, draft, 'test', preview=False)
                await db.commit()
                assert (await get_source(db, 'prompt', prompt_id)).content == 'Updated fixture guidance.'
                with pytest.raises(HTTPException) as error:
                    await apply_draft(db, draft, 'test', preview=False)
                assert error.value.status_code == 409
                await db.rollback()
                undone = await undo_change(db, saved['change_id'], 'test')
                await db.commit()
                assert undone['change_id'] != saved['change_id']
                assert (await get_source(db, 'prompt', prompt_id)).content == 'Original fixture guidance.'
                # A late failure in a bulk edit must roll back earlier valid edits.
                transaction = await db.begin_nested()
                with pytest.raises(HTTPException):
                    await apply_draft(db, ContextDraft(context=context, edits=[
                        SourceEdit(source_type='prompt', source_id=prompt_id, expected_revision=revision, content='Must roll back'),
                        SourceEdit(source_type='prompt', source_id='zz-missing-source', expected_revision='missing', enabled=False),
                    ]), 'test', preview=False)
                await transaction.rollback()
                assert (await get_source(db, 'prompt', prompt_id)).content == 'Original fixture guidance.'
                memory = await get_source(db, 'memory', memory_id)
                assert isinstance(memory, Memory)
                moved = await apply_draft(db, ContextDraft(context=context, edits=[SourceEdit(source_type='memory', source_id=memory_id, expected_revision=source_revision(memory), policy=ContextPolicy(scope='agent', targets=['coder'], required=False, activation='on_demand'), archive=True)]), 'test', preview=False)
                await db.commit()
                memory = await get_source(db, 'memory', memory_id)
                assert isinstance(memory, Memory)
                assert memory.scope == 'agent' and memory.group_id == 'agent-coder' and memory.loaded_count == 7
                await undo_change(db, moved['change_id'], 'test')
                await db.commit()
                memory = await get_source(db, 'memory', memory_id)
                assert isinstance(memory, Memory)
                assert memory.scope == 'global' and memory.status == 'active' and memory.loaded_count == 7
                # Dangling controls can be removed without resurrecting a source.
                await apply_draft(db, ContextDraft(context=context, placements=[PlacementEdit(source_type='prompt',source_id='deleted-prompt',mode='inherit')],expected_placement_revision=baseline['placement_revision']), 'test', preview=False)
        finally:
            await connection.rollback()
