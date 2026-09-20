"""Real PostgreSQL rollback, atomic save, revision and undo verification.

Only agent_hub_test is accepted. Fixture schema and data live in an
outer transaction that is always rolled back; existing test data is preserved.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
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


@pytest_asyncio.fixture
async def maintenance_db(monkeypatch):
    from unittest.mock import AsyncMock
    # Integration exercises local transactions only; never dispatch a real
    # implementation task from a fixture's deliberately invalid provider result.
    monkeypatch.setattr('app.services.context_maintenance_tasks.dispatch_technical_work', AsyncMock(return_value={'status': 'queued', 'task_id': 'test-recovery'}))
    monkeypatch.setattr('app.services.context_maintenance_tasks.reconcile_technical_work', AsyncMock(return_value={}))
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


async def maintenance_fixture(db, *, policy=None, handoff=False, kind="conflict"):
    from app.services.context_maintenance import enqueue
    from app.services.context_policy import source_snapshot
    row = Prompt(slug='maintenance-fixture', name='Maintenance fixture', content='Use the existing canonical workflow.',
        enabled=True, is_global=True, prompt_type='standard', exclude_agents=[], context_policy=(policy or ContextPolicy(scope='global')).model_dump())
    db.add(row)
    await db.flush()
    source = {**source_snapshot(row), 'revision': source_revision(row)}
    item_id = await enqueue(db, kind=kind, sources=[source], context={}, summary='Inspect conflicting guidance', recommendation='Compare the current authority.', detail={'handoff_needed': handoff})
    await db.commit()
    return row, item_id, source


@pytest.mark.integration
async def test_maintenance_dedup_scope_preview_ack_and_claims(maintenance_db):
    from app.models.context_governance import ContextMaintenanceAttention, ContextMaintenanceItem
    from app.services.context_maintenance import (
        acknowledge,
        attention_summary,
        enqueue,
        session_key,
    )
    from app.services.context_maintenance_actions import MaintenanceRequest, handle_maintenance
    from app.services.runtime_context import build_canonical_context_delivery
    db = maintenance_db
    _, item_id, source = await maintenance_fixture(db, policy=ContextPolicy(scope='project', targets=['agent-hub']))
    context = maintenance_context(project='agent-hub')
    again = await enqueue(db, kind='conflict', sources=[source], context={}, summary='Same evidence', recommendation='Same review', evidence_id='review-2')
    assert again == item_id
    assert (await attention_summary(db, context))['new_relevant'] == 0  # background work costs no startup text
    item = await db.get(ContextMaintenanceItem, item_id)
    item.detail = {'handoff_needed': True}
    assert (await attention_summary(db, context))['new_relevant'] == 0  # scheduled semantic recovery owns this
    item.detail = {'handoff_needed': True, 'technical_blocked': True}
    await db.flush()
    first = await build_canonical_context_delivery(db, context)
    second = await build_canonical_context_delivery(db, context)
    assert first.status == second.status == 'ok'
    assert first.payload_hash == second.payload_hash
    assert 'Context maintenance handoff' in first.rendered
    assert first.maintenance_attention['items'] == {item_id: 1}
    assert await db.get(ContextMaintenanceAttention, session_key(context)) is None
    assert (await attention_summary(db, maintenance_context(project='neri')))['new_relevant'] == 0
    await acknowledge(db, context, {item_id: 1})
    assert (await attention_summary(db, context))['new_relevant'] == 0
    other = maintenance_context(session='second', project='agent-hub')
    assert (await attention_summary(db, other))['new_relevant'] == 1
    claimed = await handle_maintenance(db, MaintenanceRequest(action='claim', context=context, item_id=item_id, expected_version=1, reason='Inspect evidence'), 'agent:test')
    assert claimed['item']['version'] == 2
    assert (await attention_summary(db, other))['new_relevant'] == 0
    with pytest.raises(HTTPException) as error:
        await handle_maintenance(db, MaintenanceRequest(action='claim', context=other, item_id=item_id, expected_version=2, reason='Try competing claim'), 'agent:test')
    assert error.value.status_code == 409
    assert 'Another agent' in error.value.detail
    released = await handle_maintenance(db, MaintenanceRequest(action='release', context=context, item_id=item_id, expected_version=2, reason='Hand off retained evidence'), 'agent:test')
    assert released['item']['state'] == 'pending'
    with pytest.raises(HTTPException):
        await acknowledge(db, context, {item_id: 1})


@pytest.mark.integration
async def test_maintenance_owner_question_reporting_and_answer(maintenance_db):
    from app.services.context_maintenance import attention_summary
    from app.services.context_maintenance_actions import (
        MaintenanceRequest,
        OwnerDecision,
        handle_maintenance,
    )
    db = maintenance_db
    _, item_id, _ = await maintenance_fixture(db, handoff=True)
    context = maintenance_context()
    async def action(name, version, **extra):
        return await handle_maintenance(db, MaintenanceRequest(action=name, context=context, item_id=item_id, expected_version=version, reason='Observed test evidence', **extra), 'agent:test')
    await action('claim', 1)
    with pytest.raises(HTTPException):
        await action('escalate', 2)
    await action('escalate', 2, evidence='Conflicting owner preferences in retained review', decision=OwnerDecision(question='Which scope is intended?', recommendation='Use project scope.', options=['Project', 'Global']))
    await action('reported', 3, evidence='Actual conversation message 12 contains the question')
    await action('release', 4)
    assert (await attention_summary(db, maintenance_context('second')))['new_relevant'] == 0
    answered = await handle_maintenance(db, MaintenanceRequest(action='answer', context=maintenance_context('second'), item_id=item_id, expected_version=5, reason='Project', evidence='Operator entered Project in the UI'), 'dashboard:operator', operator=True)
    assert answered['item']['state'] == 'pending'
    assert answered['item']['decision']['answer'] == 'Project'
    assert (await attention_summary(db, maintenance_context('third')))['new_relevant'] == 0
    curator_context = maintenance_context('curator').model_copy(update={'agent_slug': 'memory-curator'})
    assert (await attention_summary(db, curator_context))['new_relevant'] == 1


@pytest.mark.integration
async def test_maintenance_rejects_stale_correction_and_retains_supersession(maintenance_db):
    from app.models.context_governance import ContextMaintenanceItem
    from app.services.context_maintenance_actions import MaintenanceRequest, handle_maintenance
    from app.services.context_maintenance_reconcile import reconcile_maintenance
    db = maintenance_db
    source, item_id, snapshot = await maintenance_fixture(db, handoff=True)
    context = maintenance_context()
    await handle_maintenance(db, MaintenanceRequest(action='claim', context=context, item_id=item_id, expected_version=1, reason='Review'), 'agent:test')
    source.content = 'New owner instruction supersedes the old snapshot.'
    await db.commit()
    with pytest.raises(HTTPException) as error:
        await handle_maintenance(db, MaintenanceRequest(action='apply', context=context, item_id=item_id, expected_version=2, reason='Correct', evidence='Original authority', draft=ContextDraft(context=context, edits=[SourceEdit(source_type='prompt', source_id=source.slug, expected_revision=snapshot['revision'], content='Stale replacement')])), 'agent:test')
    assert error.value.status_code == 409
    assert source.content == 'New owner instruction supersedes the old snapshot.'
    result = await reconcile_maintenance(db)
    assert result['superseded'] == 1
    item = await db.get(ContextMaintenanceItem, item_id)
    assert item.state == 'superseded' and item.claim_owner is None
    due = list((await db.execute(select(ContextMaintenanceItem).where(ContextMaintenanceItem.kind == 'review_due'))).scalars())
    assert len(due) == 1 and due[0].sources[0]['revision'] == source_revision(source)


@pytest.mark.integration
async def test_maintenance_mechanical_repair_is_idempotent_and_rechecks_recurrence(maintenance_db):
    from app.models.context_governance import ContextMaintenanceItem
    from app.services.context_maintenance_reconcile import reconcile_maintenance
    from app.services.memory.budget import count_tokens
    db = maintenance_db
    row = Memory(content='Retain observed decisions.', name='Derived-count fixture', memory_type='reference', scope='global', tier=3, status='active', token_count=999, metadata_={})
    db.add(row)
    await db.flush()
    first = await reconcile_maintenance(db)
    assert len(first['repaired']) == 1 and first['model_calls'] == 0
    assert row.token_count == count_tokens(row.content)
    second = await reconcile_maintenance(db)
    assert second['repaired'] == []
    row.token_count = 999
    await db.flush()
    third = await reconcile_maintenance(db)
    assert third['repaired'] == first['repaired']
    assert (await db.get(ContextMaintenanceItem, first['repaired'][0])).state == 'resolved'


@pytest.mark.integration
async def test_background_review_runs_once_and_does_not_retry_uncertain_calls(maintenance_db):
    from unittest.mock import AsyncMock, patch

    from app.models.context_governance import ContextMaintenanceItem
    from app.services.context_maintenance import enqueue
    from app.services.context_maintenance_worker import run_context_maintenance
    db = maintenance_db
    _, item_id, source = await maintenance_fixture(db, kind='review_due')
    reviewer = AsyncMock(return_value=('{"findings": []}', 'catalog-model', 'review-session'))
    with patch('app.services.memory._review_agent_call._call_reviewer_agent', reviewer):
        first = await run_context_maintenance(db, batch_limit=10)
        second = await run_context_maintenance(db, batch_limit=10)
    assert first['reviewed_count'] == 1 and second['reviewed_count'] == 0
    reviewer.assert_awaited_once()
    item = await db.get(ContextMaintenanceItem, item_id)
    assert item.state == 'resolved' and item.claim_owner is None
    # A provider failure retains evidence and becomes a handoff; another
    # scheduled batch must not repeat the same uncertain provider operation.
    failed_id = await enqueue(db, kind='screening_candidate', sources=[source], context={}, summary='Candidate needs review', recommendation='Check evidence')
    await db.commit()
    reviewer.reset_mock(side_effect=True)
    reviewer.side_effect = RuntimeError('provider unavailable')
    with patch('app.services.memory._review_agent_call._call_reviewer_agent', reviewer):
        failed = await run_context_maintenance(db, batch_limit=10)
        repeated = await run_context_maintenance(db, batch_limit=10)
    assert failed['reviewed_count'] == 1 and repeated['reviewed_count'] == 0
    reviewer.assert_awaited_once()
    assert (await db.get(ContextMaintenanceItem, failed_id)).state == 'superseded'
    handoffs = list((await db.execute(select(ContextMaintenanceItem).where(ContextMaintenanceItem.kind == 'review_failed'))).scalars())
    assert len(handoffs) == 1 and handoffs[0].detail['handoff_needed']


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


@pytest.mark.integration
async def test_revision_hooks_and_grouped_background_review(maintenance_db):
    from unittest.mock import AsyncMock, patch

    from app.models.context_governance import ContextMaintenanceItem
    from app.services.context_maintenance_worker import run_context_maintenance
    from app.services.memory._repo_revisions import RevisionRepository
    from app.services.prompt_service import record_prompt_revision

    db = maintenance_db
    prompt = Prompt(slug='changed-prompt', name='Changed prompt', content='Keep source attribution.', enabled=True, is_global=True, prompt_type='standard', exclude_agents=[])
    memory = Memory(content='Observed deployment retained attribution.', name='Observed fact', memory_type='reference', scope='global', tier=3, status='active', token_count=7, metadata_={})
    db.add_all([prompt, memory])
    await db.flush()
    await record_prompt_revision(db, prompt, action='update', changed_by='test')
    await RevisionRepository().record_revision(db, memory, action='update', changed_by='test')
    await db.commit()
    items = list((await db.execute(select(ContextMaintenanceItem).where(ContextMaintenanceItem.kind == 'review_due'))).scalars())
    assert len(items) == 2
    reviewer = AsyncMock(return_value=('{"findings": []}', 'catalog-model', 'review-session'))
    with patch('app.services.memory._review_agent_call._call_reviewer_agent', reviewer):
        result = await run_context_maintenance(db, batch_limit=10)
    assert result['reviewed_count'] == 2 and result['model_calls'] == 1
    reviewer.assert_awaited_once()
    # A new revision record without a semantic source change is not new work.
    await record_prompt_revision(db, prompt, action='update', changed_by='test')
    await db.commit()
    assert all(item.state == 'resolved' for item in (await db.execute(select(ContextMaintenanceItem).where(ContextMaintenanceItem.kind == 'review_due'))).scalars())


@pytest.mark.integration
async def test_changed_reviewer_recovers_retained_failure_and_replay_makes_no_calls(maintenance_db):
    from unittest.mock import AsyncMock, patch

    from app.models.context_governance import ContextMaintenanceItem
    from app.services.context_governance import record
    from app.services.context_maintenance_worker import run_context_maintenance

    db = maintenance_db
    _, _, source = await maintenance_fixture(db, kind='review_due')
    await record(db, 'context_review', 'test', {'sources': [source], 'reviewer_identity': 'obsolete-schema',
        'coverage': {'context': {'consumer_surface': 'codex'}}, 'failure': 'Required rules must be delivered in full'})
    await db.commit()
    reviewer = AsyncMock(return_value=('{"findings": []}', 'catalog-model', 'recovered-session'))
    with patch('app.services.memory._review_agent_call._call_reviewer_agent', reviewer):
        first = await run_context_maintenance(db, batch_limit=10)
        second = await run_context_maintenance(db, batch_limit=10)
    reviewer.assert_awaited_once()
    assert first['recovery_count'] == 1
    assert second['model_calls'] == 0
    failures = list((await db.execute(select(ContextMaintenanceItem).where(ContextMaintenanceItem.kind == 'review_failed'))).scalars())
    assert failures and all(item.state == 'resolved' for item in failures)


@pytest.mark.integration
async def test_semantic_recovery_applies_exact_correction_and_retains_undo(maintenance_db):
    import json
    from unittest.mock import AsyncMock, patch

    from app.models.context_governance import ContextMaintenanceItem
    from app.services.context_maintenance_recovery import recover_item

    db = maintenance_db
    prompt, item_id, source = await maintenance_fixture(db, handoff=True, kind='targeting')
    db.add(Prompt(slug='context-maintenance-workflow', name='Maintenance', content='Correct clear scope and disclosure errors using canonical history.',
        enabled=True, is_global=False, prompt_type='standard', exclude_agents=[]))
    await db.commit()
    response = {'action': 'apply', 'reason': 'Add a faithful navigation summary without changing the rule.',
        'authority_passages': {source['source_id']: source['content']},
        'edits': [{'source_type': 'prompt', 'source_id': source['source_id'], 'expected_revision': source['revision'],
            'summary': 'Canonical workflow'}]}
    reviewer = AsyncMock(return_value=(json.dumps(response), 'catalog-model', 'recovery-session'))
    item = await db.get(ContextMaintenanceItem, item_id)
    with patch('app.services.memory._review_agent_call._call_reviewer_agent', reviewer):
        result = await recover_item(db, item, maintenance_context())
    assert 'failure' not in result
    assert item.state == 'resolved'
    assert prompt.content == source['content']
    change_id = item.resolution['change_id']
    assert item.resolution['verification'] == 'canonical_generation'
    await undo_change(db, change_id, 'test')
    await db.commit()
    restored = await get_source(db, 'prompt', source['source_id'])
    assert isinstance(restored, Prompt)
    assert restored.description == source['summary']


@pytest.mark.integration
async def test_invalid_recovery_cannot_mutate_or_repeat_inference(maintenance_db):
    import json
    from unittest.mock import AsyncMock, patch

    from app.models.context_governance import ContextMaintenanceItem
    from app.services.context_maintenance_recovery import recover_item

    db = maintenance_db
    _, item_id, source = await maintenance_fixture(db, handoff=True)
    db.add(Prompt(slug='context-maintenance-workflow', name='Maintenance', content='Preserve authority and exact evidence.',
        enabled=True, is_global=False, prompt_type='standard', exclude_agents=[]))
    await db.commit()
    response = {'action': 'apply', 'reason': 'An unsupported edit', 'authority_passages': {source['source_id']: 'Invented passage'},
        'edits': [{'source_type': 'prompt', 'source_id': source['source_id'], 'expected_revision': source['revision'], 'content': 'Must never be saved'}]}
    reviewer = AsyncMock(return_value=(json.dumps(response), 'catalog-model', 'recovery-session'))
    with patch('app.services.memory._review_agent_call._call_reviewer_agent', reviewer):
        first = await recover_item(db, await db.get(ContextMaintenanceItem, item_id), maintenance_context())
        second = await recover_item(db, await db.get(ContextMaintenanceItem, item_id), maintenance_context())
    reviewer.assert_awaited_once()
    assert first['failure'] == 'ValueError' and second['model_calls'] == 0
    assert (await get_source(db, 'prompt', source['source_id'])).content == source['content']
    receipts = list((await db.execute(select(ContextRecord).where(ContextRecord.kind == 'maintenance_recovery'))).scalars())
    assert len(receipts) == 1 and 'Invented passage' in receipts[0].payload['response']


@pytest.mark.integration
async def test_recovery_rejects_edits_outside_maintenance_item_sources(maintenance_db):
    import json
    from unittest.mock import AsyncMock, patch

    from app.models.context_governance import ContextMaintenanceItem
    from app.services.context_maintenance_recovery import recover_item
    from app.services.context_policy import ContextPolicy

    db = maintenance_db
    _, item_id, source = await maintenance_fixture(db, handoff=True)
    neighbor = Prompt(slug='neighbor-fixture', name='Neighbor fixture', content='Use the existing canonical workflow in this other source.',
        enabled=True, is_global=True, prompt_type='standard', exclude_agents=[], context_policy=ContextPolicy(scope='global').model_dump())
    db.add(neighbor)
    db.add(Prompt(slug='context-maintenance-workflow', name='Maintenance', content='Preserve authority and exact evidence.',
        enabled=True, is_global=False, prompt_type='standard', exclude_agents=[]))
    await db.commit()
    from app.services.context_policy import source_revision
    response = {'action': 'apply', 'reason': 'Wrong item edit', 'authority_passages': {neighbor.slug: neighbor.content},
        'edits': [{'source_type': 'prompt', 'source_id': neighbor.slug, 'expected_revision': source_revision(neighbor), 'content': 'Must never be saved'}]}
    reviewer = AsyncMock(return_value=(json.dumps(response), 'catalog-model', 'recovery-session'))
    with patch('app.services.memory._review_agent_call._call_reviewer_agent', reviewer):
        result = await recover_item(db, await db.get(ContextMaintenanceItem, item_id), maintenance_context())
    reviewer.assert_awaited_once()
    assert result['failure'] == 'ValueError'
    assert neighbor.content == 'Use the existing canonical workflow in this other source.'
    assert (await get_source(db, 'prompt', source['source_id'])).content == source['content']
    receipts = list((await db.execute(select(ContextRecord).where(ContextRecord.kind == 'maintenance_recovery'))).scalars())
    assert len(receipts) == 1 and 'neighbor-fixture' in receipts[0].payload['response']


@pytest.mark.integration
async def test_later_review_failure_reopens_resolved_incident_once(maintenance_db):
    from app.models.context_governance import ContextMaintenanceItem
    from app.services.context_governance import record
    db = maintenance_db
    _, _, source = await maintenance_fixture(db, kind='review_due')
    packet = {'sources': [source], 'reviewer': {'agent_slug': 'memory-curator'}, 'coverage': {'context': {}}}
    await record(db, 'context_review', 'test', {**packet, 'failure': 'Original unavailable provider'})
    item = (await db.execute(select(ContextMaintenanceItem).where(ContextMaintenanceItem.kind == 'review_failed'))).scalar_one()
    item.detail = {**item.detail, 'technical_work': {'task_id': 'original-repair', 'status': 'completed_pending_revalidation'}}
    await record(db, 'context_review', 'test', packet)
    assert item.state == 'resolved'
    latest = await record(db, 'context_review', 'test', {**packet, 'failure': 'Later provider failure'})
    assert item.state == 'pending' and item.detail['generation'] == 1
    assert 'technical_work' not in item.detail and item.detail['handoff_needed']
    from app.services.context_maintenance import ingest_review
    await ingest_review(db, await db.get(ContextRecord, latest))
    assert item.detail['generation'] == 1
    history = list((await db.execute(select(ContextRecord).where(ContextRecord.kind == 'maintenance'))).scalars())
    assert any(row.payload.get('action') == 'review_failure_recurred' and
        row.payload['evidence']['detail']['technical_work']['task_id'] == 'original-repair' for row in history)


@pytest.mark.integration
async def test_changed_review_keeps_competing_claim_and_rejected_dismissal(maintenance_db):
    import json
    from unittest.mock import AsyncMock, patch

    from app.models.context_governance import ContextMaintenanceItem
    from app.services.context_maintenance_recovery import RecoveryDecision, _retry_changed_review
    db = maintenance_db
    _, item_id, _ = await maintenance_fixture(db, handoff=True, kind='review_failed')
    item = await db.get(ContextMaintenanceItem, item_id)
    async def competing_review(*args, **kwargs):
        item.claim_owner, item.claim_session = 'agent:interactive', 'other-session'
        item.version += 1
        await db.commit()
        return json.dumps({'findings': []}), 'catalog-model', 'review-session'
    with patch('app.services.memory._review_agent_call._call_reviewer_agent', AsyncMock(side_effect=competing_review)):
        result = await _retry_changed_review(db, item, maintenance_context(), 'corrected-reviewer')
    assert 'ownership changed' in result['failure']
    assert item.state == 'claimed' and item.claim_owner == 'agent:interactive'
    from pydantic import ValidationError
    with pytest.raises(ValidationError, match='exact supporting source passages'):
        RecoveryDecision(action='dismiss', reason='Unsupported model assertion')


@pytest.mark.integration
async def test_regular_review_failure_reservation_and_changed_input_recovery(maintenance_db):
    from unittest.mock import AsyncMock, patch

    from app.models.context_governance import ContextMaintenanceItem
    from app.models.memory_unified import MemoryReviewRun
    from app.services.memory import _review_agent_runner as runner
    from app.services.memory._review_agent_decisions import MemoryReviewDecision

    db = maintenance_db
    memory = Memory(content='A dated fixture records an observed successful delivery.', name='Recovery fixture',
        memory_type='reference', scope='global', tier=3, status='active', token_count=10, metadata_={})
    db.add(memory)
    await db.commit()
    sources = runner._memory_review_sources([memory])
    prepared = runner._ReviewInputs(prompt='Frozen evidence', sources=sources, evidence={}, reviewer_identity='before-fix', attempt_key='frozen-failure')
    provider = AsyncMock(side_effect=RuntimeError('Provider unavailable'))
    with (patch.object(runner, '_load_batch_memories', AsyncMock(return_value=[memory])),
          patch.object(runner, '_prepare_review_inputs', AsyncMock(return_value=prepared)),
          patch.object(runner, '_call_review_for_memories', provider)):
        first = await runner.run_memory_review_batch(db=db, batch_limit=1)
        await db.commit()
        second = await runner.run_memory_review_batch(db=db, batch_limit=1, force_all=True)
        await db.commit()
    assert first.status == 'failed' and second.status == 'blocked'
    provider.assert_awaited_once()
    runs = list((await db.execute(select(MemoryReviewRun))).scalars())
    assert len(runs) == 1 and runs[0].metadata_['attempt']['status'] == 'failed'
    failures = list((await db.execute(select(ContextMaintenanceItem).where(ContextMaintenanceItem.kind == 'review_failed'))).scalars())
    assert len(failures) == 1
    decision = MemoryReviewDecision(uuid=str(memory.id), decision='keep', review_status='clean', confidence=1,
        reason='Exact fixture retained.', checks={key: 'pass' for key in ('currency', 'correctness', 'appropriateness',
            'scope_applicability', 'conflict', 'redundancy', 'lifecycle', 'authority', 'token_efficiency')})
    prepared = runner._ReviewInputs(prompt='Frozen evidence', sources=sources, evidence={}, reviewer_identity='after-fix', attempt_key='corrected-reviewer')
    with (patch.object(runner, '_load_batch_memories', AsyncMock(return_value=[memory])),
          patch.object(runner, '_prepare_review_inputs', AsyncMock(return_value=prepared)),
          patch.object(runner, '_call_review_for_memories', AsyncMock(return_value=('{}', 'catalog-model', 'fixed-session'))),
          patch('app.services.memory.review_agent.parse_memory_review_content', return_value=[decision])):
        recovered = await runner.run_memory_review_batch(db=db, batch_limit=1)
        await db.commit()
    assert recovered.status == 'completed'
    assert failures[0].state == 'resolved'
    assert memory.content == sources[0]['content']


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
