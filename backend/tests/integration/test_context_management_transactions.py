"""Real PostgreSQL rollback, atomic save, revision and undo verification.

Only agent_hub_test is accepted. Fixture schema and data live in an
outer transaction that is always rolled back; existing test data is preserved.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import _get_engine
from app.models import Base
from app.models.context_governance import ContextMaintenanceItem, ContextRecord
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


@pytest.mark.integration
async def test_service_scope_move_preserves_content_and_undo_receipt(maintenance_db, monkeypatch):
    from app.services.context_governance import (
        MemoryScopeApplyRequest,
        MemoryScopePreviewRequest,
        apply_memory_scope,
        preview_memory_scope,
    )

    db = maintenance_db
    monkeypatch.setattr(
        "app.core.project_roots.get_registered_project_roots",
        AsyncMock(return_value={"agent-hub": "/tmp/agent-hub"}),
    )
    row = Memory(
        content="Keep the exact procedure text and prior revisions.",
        name="Scope move fixture", memory_type="reference", scope="global",
        tier=3, status="active", metadata_={},
    )
    db.add(row)
    await db.flush()
    initial_revision = source_revision(row)
    request = MemoryScopePreviewRequest(
        memory_id=str(row.id)[:8], scope="project", scope_id="agent-hub", reason="Correct project targeting",
    )
    client = {"id": "internal-test", "client_type": "internal", "allowed_projects": '["agent-hub"]'}
    monkeypatch.setattr("app.middleware.access_control_auth.settings.agent_hub_admin_client_ids", ("internal-test",))
    preview = await preview_memory_scope(db, request, client)
    await db.refresh(row)
    assert preview["expected_revision"] == initial_revision
    assert preview["content_unchanged"] is True
    assert row.scope == "global" and source_revision(row) == initial_revision

    applied = await apply_memory_scope(db, MemoryScopeApplyRequest(
        **request.model_dump(), expected_revision=initial_revision,
    ), client)
    await db.flush()
    assert applied["revision"] == source_revision(row)
    assert applied["change_id"]
    assert row.scope == "project" and row.scope_id == "agent-hub"
    assert row.content == "Keep the exact procedure text and prior revisions."
    from app.models.memory_unified import MemoryRevision

    revisions = list((await db.execute(select(MemoryRevision).where(MemoryRevision.memory_id == row.id))).scalars())
    assert any(revision.scope == "project" and revision.content == row.content and
               revision.changed_by == "service:internal-test" for revision in revisions)
    with pytest.raises(HTTPException) as stale:
        await apply_memory_scope(db, MemoryScopeApplyRequest(
            **request.model_dump(), expected_revision=initial_revision,
        ), client)
    assert stale.value.status_code == 409
    await undo_change(db, applied["change_id"], "test:undo")
    await db.flush()
    assert row.scope == "global" and row.scope_id is None
    assert row.content == "Keep the exact procedure text and prior revisions."


@pytest_asyncio.fixture
async def maintenance_db():
    async with _get_engine().connect() as connection:
        assert (await connection.execute(text('SELECT current_database()'))).scalar() == 'agent_hub_test'
        try:
            await connection.run_sync(apply_test_migrations)
            async with AsyncSession(bind=connection, expire_on_commit=False, join_transaction_mode='create_savepoint') as db:
                yield db
        finally:
            await connection.rollback()


def maintenance_context(session="first", project=None):
    return CanonicalContextDeliveryRequest(consumer_surface='codex', session_id=session, project_id=project,
        capabilities=['bash'], include_memories=False, include_project_index=False, include_tool_capabilities=False, include_continuity=False)


async def insert_maintenance_item(db, *, kind, sources, summary, recommendation, evidence_ids=None, detail=None):
    """Insert a retained maintenance row directly; nothing creates new ones."""
    row = ContextMaintenanceItem(
        id=str(uuid.uuid4()), fingerprint=uuid.uuid4().hex, kind=kind, state='pending', version=1,
        summary=summary, recommendation=recommendation, sources=sources, context={},
        source_keys=sorted({source['source_id'] for source in sources}), evidence_ids=list(evidence_ids or []),
        detail=detail or {}, decision={}, resolution={},
    )
    db.add(row)
    await db.flush()
    return row.id


async def maintenance_fixture(db, *, policy=None, handoff=False, kind="conflict", detail=None, evidence_ids=None):
    """Seed a retained maintenance item; new reviews no longer create them."""
    from app.services.context_policy import source_snapshot
    row = Prompt(slug='maintenance-fixture', name='Maintenance fixture', content='Use the existing canonical workflow.',
        enabled=True, is_global=True, prompt_type='standard', exclude_agents=[], context_policy=(policy or ContextPolicy(scope='global')).model_dump())
    db.add(row)
    await db.flush()
    source = {**source_snapshot(row), 'revision': source_revision(row)}
    item_id = await insert_maintenance_item(db, kind=kind, sources=[source], summary='Inspect conflicting guidance',
        recommendation='Compare the current authority.', evidence_ids=evidence_ids,
        detail={'handoff_needed': handoff, **(detail or {})})
    await db.commit()
    return row, item_id, source


RETIRED_MAINTENANCE_ACTIONS = ('acknowledge', 'claim', 'release', 'recover', 'defer', 'resume', 'dismiss', 'escalate',
    'reported', 'answer', 'repair', 'apply', 'resolve', 'review', 'reconcile', 'verify_work')


@pytest.mark.integration
async def test_manual_maintenance_lists_and_inspects_retained_items(maintenance_db):
    from app.services.context_maintenance_actions import MaintenanceRequest, handle_maintenance
    db = maintenance_db
    _, item_id, source = await maintenance_fixture(
        db, policy=ContextPolicy(scope='project', targets=['agent-hub']), handoff=True, evidence_ids=['review-2'])
    background_id = await insert_maintenance_item(db, kind='review_due', sources=[source], summary='Background review',
        recommendation='Review the changed source.')
    await db.commit()
    context = maintenance_context(project='agent-hub')

    listed = await handle_maintenance(db, MaintenanceRequest(action='list', context=context), 'agent:test')
    assert [item['id'] for item in listed['items']] == [item_id]
    assert listed['items'][0]['handoff_needed'] is True and 'sources' not in listed['items'][0]
    assert listed['background_items'] == 1
    assert listed['guidance'] is None and listed['guidance_source'] is None
    assert listed['health']['state'] == 'retired' and listed['health']['schedule_enabled'] is False
    assert listed['health']['active_counts'] == {'pending': 2}
    assert listed['attention']['new_relevant'] == 0  # retained items no longer demand startup attention
    everything = await handle_maintenance(db, MaintenanceRequest(action='list', context=context, include_background=True), 'agent:test')
    assert {item['id'] for item in everything['items']} == {item_id, background_id}

    other_project = maintenance_context(project='neri')
    unrelated = await handle_maintenance(db, MaintenanceRequest(action='list', context=other_project, include_background=True), 'agent:test')
    assert unrelated['items'] == [] and unrelated['background_items'] == 0

    inspected = await handle_maintenance(db, MaintenanceRequest(action='inspect', context=context, item_id=item_id), 'agent:test')
    assert inspected['item']['id'] == item_id and inspected['item']['version'] == 1
    assert inspected['item']['sources'][0]['revision'] == source['revision']
    assert inspected['item']['evidence_ids'] == ['review-2']
    assert inspected['reviews'] == [] and inspected['history'] == []
    with pytest.raises(HTTPException) as hidden:
        await handle_maintenance(db, MaintenanceRequest(action='inspect', context=other_project, item_id=item_id), 'agent:test')
    assert hidden.value.status_code == 404


@pytest.mark.integration
async def test_delivery_no_longer_injects_maintenance_handoff(maintenance_db, monkeypatch):
    from app.models.context_governance import ContextMaintenanceAttention, ContextMaintenanceItem
    from app.services.context_maintenance import session_key
    from app.services.runtime_context import build_canonical_context_delivery
    # CI has no `st`; delivery reads the SummitFlow project registry through it.
    monkeypatch.setattr('app.core.project_roots.get_registered_project_roots',
                        AsyncMock(return_value={'agent-hub': '/srv/workspaces/projects/agent-hub'}))
    db = maintenance_db
    _, item_id, _ = await maintenance_fixture(db, policy=ContextPolicy(scope='project', targets=['agent-hub']),
        handoff=True, detail={'technical_blocked': True})
    context = maintenance_context(project='agent-hub')
    first = await build_canonical_context_delivery(db, context)
    second = await build_canonical_context_delivery(db, context)
    assert first.status == second.status == 'ok'
    assert first.payload_hash == second.payload_hash
    assert 'Use the existing canonical workflow.' in first.rendered
    assert 'Context maintenance handoff' not in first.rendered
    assert first.maintenance_attention == {}
    assert not any(block.kind == 'context_maintenance' for block in first.blocks)
    assert await db.get(ContextMaintenanceAttention, session_key(context)) is None
    item = await db.get(ContextMaintenanceItem, item_id)
    assert item.state == 'pending' and item.version == 1


@pytest.mark.integration
async def test_retired_maintenance_execution_returns_410_without_mutation(maintenance_db):
    from unittest.mock import patch

    from app.models.context_governance import ContextMaintenanceItem
    from app.services.context_maintenance import reconcile_maintenance
    from app.services.context_maintenance_actions import (
        MaintenanceRequest,
        handle_maintenance,
        recover_item,
    )
    db = maintenance_db
    prompt, item_id, source = await maintenance_fixture(db, handoff=True)
    context = maintenance_context()
    draft = ContextDraft(context=context, edits=[SourceEdit(source_type='prompt', source_id=prompt.slug,
        expected_revision=source['revision'], content='Must never be saved')])
    for action in RETIRED_MAINTENANCE_ACTIONS:
        with pytest.raises(HTTPException) as retired:
            await handle_maintenance(db, MaintenanceRequest(action=action, context=context, item_id=item_id, expected_version=1,
                reason='Observed test evidence', evidence='Retained evidence', draft=draft), 'agent:test', operator=True)
        assert retired.value.status_code == 410, action
        assert 'retired' in retired.value.detail
    reviewer = AsyncMock()
    with patch('app.services.memory._review_agent_call._call_reviewer_agent', reviewer):
        for retired_call in (recover_item(db, await db.get(ContextMaintenanceItem, item_id), context), reconcile_maintenance(db)):
            with pytest.raises(HTTPException) as retired:
                await retired_call
            assert retired.value.status_code == 410
    reviewer.assert_not_awaited()
    item = await db.get(ContextMaintenanceItem, item_id)
    assert item.state == 'pending' and item.version == 1 and item.claim_owner is None
    assert (await get_source(db, 'prompt', prompt.slug)).content == 'Use the existing canonical workflow.'
    assert not list((await db.execute(select(ContextRecord))).scalars())


@pytest.mark.integration
async def test_manual_routes_inventory_save_undo_and_maintenance(maintenance_db):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.api.runtime_context import router as runtime_context_router
    from app.db import get_db
    from app.models.context_governance import ContextMaintenanceItem
    from app.services.api_key_auth import require_api_key
    db = maintenance_db
    prompt, item_id, source = await maintenance_fixture(db, handoff=True)
    slug = prompt.slug  # rollbacks after rejected requests expire ORM rows

    async def session_override():
        yield db

    app = FastAPI()
    app.include_router(runtime_context_router, prefix='/api')
    app.dependency_overrides[get_db] = session_override
    app.dependency_overrides[require_api_key] = lambda: None
    context = maintenance_context().model_dump(mode='json')
    base = '/api/runtime-context/manage'
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        inventory_response = await client.post(f'{base}/inventory', json=context)
        assert inventory_response.status_code == 200
        listed = {s['source_id']: s for s in inventory_response.json()['sources'] if s['source_type'] == 'prompt'}
        assert listed[slug]['revision'] == source['revision']
        assert listed[slug]['state'] == 'included'

        def save_body(revision, content):
            return {'context': context, 'reason': 'Manual maintenance correction', 'edits': [
                {'source_type': 'prompt', 'source_id': slug, 'expected_revision': revision, 'content': content}]}

        stale = await client.post(f'{base}/save', json=save_body('stale-revision', 'Stale replacement'))
        assert stale.status_code == 409
        assert (await get_source(db, 'prompt', slug)).content == 'Use the existing canonical workflow.'

        saved = await client.post(f'{base}/save', json=save_body(source['revision'], 'Use the corrected canonical workflow.'))
        assert saved.status_code == 200
        change_id = saved.json()['change_id']
        assert (await get_source(db, 'prompt', slug)).content == 'Use the corrected canonical workflow.'
        change = await db.get(ContextRecord, change_id)
        assert change.kind == 'change' and change.actor == 'dashboard:operator'
        # Manual saves are retained history only; they no longer queue curator review work.
        items = list((await db.execute(select(ContextMaintenanceItem))).scalars())
        assert [item.id for item in items] == [item_id]

        history_response = await client.get(f'{base}/history', params={'source_id': slug})
        assert [entry['id'] for entry in history_response.json()] == [change_id]

        maintenance_list = await client.post(f'{base}/maintenance', json={'action': 'list', 'context': context})
        assert maintenance_list.status_code == 200
        assert [item['id'] for item in maintenance_list.json()['items']] == [item_id]
        claim = await client.post(f'{base}/maintenance', json={'action': 'claim', 'context': context, 'item_id': item_id,
            'expected_version': 1, 'reason': 'Inspect evidence'})
        assert claim.status_code == 410 and 'retired' in claim.json()['detail']

        undone = await client.post(f'{base}/changes/{change_id}/undo')
        assert undone.status_code == 200 and undone.json()['change_id'] != change_id
        assert (await get_source(db, 'prompt', slug)).content == 'Use the existing canonical workflow.'


@pytest.mark.integration
async def test_evaluation_fixtures_never_create_operational_handoffs(maintenance_db):
    from app.models.context_governance import ContextMaintenanceItem
    from app.services.context_governance import record
    db = maintenance_db
    await record(db, 'context_screen', 'context-evaluation', {
        'sources': [{'source_type': 'fixture', 'source_id': 'case:a', 'revision': 'abc'}, {'source_type': 'fixture', 'source_id': 'case:b', 'revision': 'def'}],
        'entries': [{'pair': ['case:a', 'case:b'], 'result': {'answers': {'relationship': {'choice': 'conflict'}}}}],
    })
    assert not list((await db.execute(select(ContextMaintenanceItem))).scalars())


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
                from unittest.mock import patch

                from scripts.export_seeds import PUBLIC_PROMPT_SLUGS, export_seeds
                with patch('scripts.export_seeds.PUBLIC_PROMPT_SLUGS', PUBLIC_PROMPT_SLUGS | {scoped.slug}):
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


@pytest.mark.integration
async def test_excluding_global_context_is_noted_after_commit_and_never_after_rollback(maintenance_db, monkeypatch):
    """Excluding a global guardrail for every project (overrides or the editor) tells the owner; a rollback does not."""
    import asyncio

    from app.services import global_context_notes
    from app.services.runtime_context import (
        RuntimeContextOverridePayload,
        replace_runtime_context_overrides,
    )

    sent = []

    async def fake_send(note):
        sent.append(note)

    monkeypatch.setattr(global_context_notes, 'send_note', fake_send)
    # CI has no `st`; delivery reads the SummitFlow project registry through it.
    monkeypatch.setattr('app.core.project_roots.get_registered_project_roots',
                        AsyncMock(return_value={'agent-hub': '/srv/workspaces/projects/agent-hub'}))
    db = maintenance_db
    guardrail = Prompt(slug='exclusion-note-guardrail', name='Guardrail', content='Never expose secrets.',
                       enabled=True, is_global=True, prompt_type='global_guardrail', exclude_agents=[],
                       context_policy=ContextPolicy(scope='global').model_dump())
    plain = Prompt(slug='exclusion-note-plain', name='Plain', content='Project advice.', enabled=True,
                   is_global=False, prompt_type='standard', exclude_agents=[],
                   context_policy=ContextPolicy(scope='project', targets=['agent-hub']).model_dump())
    db.add_all([guardrail, plain])
    await db.commit()

    def excluded(*slugs):
        return [RuntimeContextOverridePayload(source_type='prompt', source_id=slug, mode='exclude') for slug in slugs]

    await replace_runtime_context_overrides(db, consumer_profile='codex', project_id=None,
                                            overrides=excluded('exclusion-note-guardrail', 'exclusion-note-plain'))
    await asyncio.gather(*list(global_context_notes._tasks))
    assert [(n.title, n.name, n.excluded_from) for n in sent] == [
        ('Global prompt excluded', 'exclusion-note-guardrail', 'codex context in every project')]

    # Replacing the layer with the same exclusion is not a new exclusion.
    await replace_runtime_context_overrides(db, consumer_profile='codex', project_id=None,
                                            overrides=excluded('exclusion-note-guardrail'))
    await asyncio.gather(*list(global_context_notes._tasks))
    assert len(sent) == 1

    context = maintenance_context(project='agent-hub')
    placements = await inventory(db, context)
    draft = ContextDraft(context=context, expected_placement_revision=placements['placement_revision'],
                         placements=[PlacementEdit(source_type='prompt', source_id='exclusion-note-guardrail', mode='exclude')])
    await apply_draft(db, draft, 'dashboard:operator', preview=False)
    await db.rollback()
    await asyncio.gather(*list(global_context_notes._tasks))
    assert len(sent) == 1

    await apply_draft(db, draft, 'dashboard:operator', preview=False)
    await db.commit()
    await asyncio.gather(*list(global_context_notes._tasks))
    assert len(sent) == 2
    assert sent[1].excluded_from == 'agent_startup context in project agent-hub'
    assert sent[1].changed_by == 'dashboard:operator'
