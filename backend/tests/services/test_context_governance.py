"""Regression cases for scope leaks, stale edits, draft rollback and cache identity."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.prompt import Prompt
from app.services.context_governance import (
    ContextDraft,
    SourceEdit,
    apply_source_edit,
    preview_draft,
)
from app.services.context_policy import ContextPolicy, policy_match, source_revision
from app.services.context_review import deterministic_findings
from app.services.context_screening import screening_identity
from app.services.runtime_context import CanonicalContextDeliveryRequest, _build_prompt_blocks


def prompt(**changes):
    return Prompt(**{"slug": "research", "name": "Research", "content": "Use the research workflow.",
        "description": "Research instructions", "enabled": True, "is_global": False, "boot_eligible": False,
        "exclude_agents": [], "prompt_type": "standard", "context_policy": ContextPolicy(
            scope="project", targets=["security-research"], workflows=["security-research"]).model_dump(), **changes})


@pytest.mark.parametrize(("project", "workflows", "expected"), [
    (None, [], False), ("agent-hub", [], False), ("security-research", [], True),
    ("agent-hub", ["security-research"], True),
])
@pytest.mark.asyncio
async def test_security_policy_requires_scope_or_explicit_workflow(project, workflows, expected):
    row = prompt()
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [row]
    db.execute.return_value = result
    context = CanonicalContextDeliveryRequest(consumer_surface="codex", project_id=project, workflow_ids=workflows)
    blocks = await _build_prompt_blocks(db, [], {}, set(), delivery_request=context)
    assert bool(blocks) is expected
    if blocks:
        assert blocks[0].required
        assert blocks[0].content == row.content


def test_workflow_never_bypasses_consumer_exclusion():
    policy = ContextPolicy(scope="project", targets=["security-research"], workflows=["security-research"], applicability={"exclude_consumer_surfaces": ["codex"]})
    assert not policy_match(policy, CanonicalContextDeliveryRequest(consumer_surface="codex", workflow_ids=["security-research"]))[0]


def test_invalid_targeting_and_required_compaction_rejected():
    for params in ({"scope": "project"}, {"required": True, "format": "summary"},
                   {"activation": "triggered"}, {"applicability": {"exclude_surface_typo": ["codex"]}},
                   {"required": True, "activation": "on_demand"}):
        with pytest.raises(ValidationError):
            ContextPolicy(**params)


@pytest.mark.parametrize("render_format", ["full", "compact", "summary"])
@pytest.mark.asyncio
async def test_on_demand_index_has_no_full_procedure_and_explicit_request_loads_it(render_format):
    row = prompt(content="Procedure secret body. Do all twelve steps.", context_policy=ContextPolicy(scope="global", required=False, activation="on_demand", format=render_format).model_dump())
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [row]
    db.execute.return_value = result
    request = CanonicalContextDeliveryRequest(consumer_surface="codex")
    indexed = await _build_prompt_blocks(db, [], {}, set(), delivery_request=request)
    assert indexed[0].disclosure == "index"
    assert row.content not in indexed[0].content
    loaded = await _build_prompt_blocks(db, [], {}, set(), delivery_request=request.model_copy(update={"requested_source_ids": ["research"]}))
    assert loaded[0].content == row.content
    assert loaded[0].disclosure == "full"


@pytest.mark.asyncio
async def test_stale_scope_edit_rejected_before_mutation():
    row = prompt()
    before = source_revision(row)
    edit = SourceEdit(source_type="prompt", source_id=row.slug, expected_revision=before, content="Stale overwrite")
    row.content = "Changed by another operator"
    with (patch("app.services.context_governance.get_source", new=AsyncMock(return_value=row)),
          pytest.raises(HTTPException) as error):
        await apply_source_edit(AsyncMock(), edit, "operator", "test", preview=False)
    assert error.value.status_code == 409
    assert row.content == "Changed by another operator"


@pytest.mark.asyncio
async def test_draft_rolls_back_even_if_canonical_assembly_fails():
    db = AsyncMock()
    db.expire_all = MagicMock()
    transaction = AsyncMock()
    db.begin_nested.return_value = transaction
    with (patch("app.services.context_governance.inventory", new=AsyncMock(return_value={})),
          patch("app.services.context_governance.apply_draft", new=AsyncMock(side_effect=RuntimeError("assembly failed"))),
          pytest.raises(RuntimeError)):
        await preview_draft(db, ContextDraft(context=CanonicalContextDeliveryRequest(consumer_surface="codex")))
    transaction.rollback.assert_awaited_once()
    db.commit.assert_not_awaited()
    db.expire_all.assert_called_once()


def test_semantic_cache_ignores_counters_titles_revision_labels_and_display_weights():
    first = {"source_id": "a", "content": "Use canonical tooling", "policy": {"scope": "global"}, "name": "A"}
    second = {"source_id": "b", "content": "Use canonical tooling before changes", "policy": {"scope": "global"}}
    context = {"consumer_surface": "codex", "project_id": "agent-hub"}
    key, _ = screening_identity(first, second, context, "jev-1.13.0")
    assert screening_identity({**first, "name": "New name", "loaded_count": 98, "revision": "display-edit"}, second, {**context, "display_weights": [1, 3]}, "jev-1.13.0")[0] == key
    assert screening_identity({**first, "content": "Never use canonical tooling"}, second, context, "jev-1.13.0")[0] != key
    assert screening_identity(first, second, {**context, "project_id": "neri"}, "jev-1.13.0")[0] != key
    assert screening_identity(first, second, context, "jev-1.14.0")[0] != key


def test_exact_duplicate_findings_retain_both_passages():
    findings = deterministic_findings([{"source_id": "a", "content": "Use ST"}, {"source_id": "b", "content": "Use  ST"}])
    assert findings[0]["source_ids"] == ["a", "b"]
    assert findings[0]["passages"] == {"a": "Use ST", "b": "Use  ST"}


@pytest.mark.asyncio
async def test_citation_does_not_infer_helpfulness():
    from app.services.memory.session_analysis import _credit_citations
    with (patch("app.services.memory.session_analysis.get_cited_memories", new=AsyncMock(return_value=[])),
          patch("app.services.memory.session_analysis.track_referenced_batch", new=AsyncMock()) as cited,
          patch("app.services.memory.session_analysis.store_cite_event", new=AsyncMock()),
          patch("app.services.memory.session_analysis.update_citation_metrics", new=AsyncMock()),
          patch("app.services.memory.usage_tracker.track_helpful") as helpful):
        assert await _credit_citations("session", ["memory"]) == 1
        cited.assert_awaited_once_with(["memory"])
        helpful.assert_not_called()


def test_jev_catalog_entry_is_typed_and_not_chat():
    from app.constants.catalog_entries import MODEL_CATALOG
    from app.services.model_catalog_service import _entry_values
    entry = next(model for model in MODEL_CATALOG if model.id == "jev-1.13.0")
    assert entry.capabilities.supports_typed_judgment
    assert not entry.capabilities.supports_chat
    assert not entry.capabilities.supports_tool_execution
    assert _entry_values(entry, 1)["cost_input_per_m"] == 0.042
    assert entry.capabilities.max_state_question_tokens == 32000


@pytest.mark.parametrize(('include_global', 'requested', 'expected'), [(False, False, None), (True, False, 'index'), (True, True, 'full')])
@pytest.mark.asyncio
async def test_memory_on_demand_index_scope_and_explicit_full_content(include_global, requested, expected):
    from uuid import uuid4

    from app.models.memory_unified import Memory
    from app.services.memory.context_builder import ProgressiveContext
    from app.services.runtime_context import _build_memory_blocks
    row = Memory(id=uuid4(), content='Full detailed memory instructions that must not appear in the passive index.', summary='Short approved summary', name='On demand', loaded_count=0, referenced_count=0, pinned=False, memory_type='reference', status='active', scope='global', tier=3, render_mode='compact', metadata_={'compact_content': 'Approved compact form', 'disclosure': {'activation': 'on_demand'}}, tags=[])
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value = [row]
    db.execute.return_value = result
    request = CanonicalContextDeliveryRequest(consumer_surface='codex', include_global=include_global, requested_source_ids=[str(row.id)] if requested else [])
    with (patch('app.services.runtime_context.build_progressive_context', new=AsyncMock(return_value=ProgressiveContext())),
          patch('app.services.runtime_context._fetch_forced_memory_items', new=AsyncMock(return_value=[])),
          patch('app.services.runtime_context._load_memory_source_revisions', new=AsyncMock(return_value={}))):
        blocks = await _build_memory_blocks(db, consumer_profile='agent_startup', consumer_surface='codex', agent_slug=None, consumer_tags=[], project_id=None, query='startup', task_type=None, phase=None, include_global=include_global, include_mandates=True, include_guardrails=True, include_references=True, include_reference_index=True, exclude_tags=[], exclude_memory_uuids=[], variant=None, overrides=[], override_by_key={}, excluded=set(), delivery_request=request)
    if expected is None:
        assert blocks == []
    elif expected == 'index':
        assert blocks[0].disclosure == 'index'
        assert row.content not in blocks[0].content
        assert str(row.id) in blocks[0].content
    else:
        assert blocks[0].content == row.content


@pytest.mark.asyncio
async def test_explicit_review_compares_pairs_even_without_lexical_overlap():
    from app.services.context_review import ContextReviewRequest, prepare_review
    sources = [{'source_id': key, 'source_type': 'prompt', 'revision': key, 'content': content, 'owner_agent_id': None, 'enabled': True, 'policy': ContextPolicy(scope='global').model_dump()} for key, content in [('a', 'Require approval.'), ('b', 'Proceed autonomously.')]]
    with patch('app.services.context_review.inventory', new=AsyncMock(return_value={'sources': sources})):
        result = await prepare_review(AsyncMock(), ContextReviewRequest(context=CanonicalContextDeliveryRequest(consumer_surface='codex'), source_ids=['a', 'b']))
    assert result['pairs'] == [['a', 'b']]
    assert result['coverage']['candidate_method'] == 'all selected pairs'


@pytest.mark.asyncio
async def test_review_respects_task_triggers_and_excluded_placements():
    from app.services.context_review import ContextReviewRequest, prepare_review
    policies = [ContextPolicy(scope='global', activation='triggered', task_types=['review']), ContextPolicy(scope='global')]
    sources = [{'source_id': str(i), 'source_type': 'prompt', 'revision': str(i), 'content': 'Use review workflow.', 'owner_agent_id': None, 'enabled': True, 'policy': policy.model_dump()} for i, policy in enumerate(policies)]
    context = CanonicalContextDeliveryRequest(consumer_surface='codex', task_type='coding')
    with patch('app.services.context_review.inventory', new=AsyncMock(return_value={'sources': sources})):
        result = await prepare_review(AsyncMock(), ContextReviewRequest(context=context, source_ids=['0', '1']))
    assert result['pairs'] == []
    assert result['coverage']['eligible_sources'] == 1
    sources[0]['policy'] = policies[1].model_dump()
    sources[0]['state'] = 'excluded here'
    with patch('app.services.context_review.inventory', new=AsyncMock(return_value={'sources': sources})):
        result = await prepare_review(AsyncMock(), ContextReviewRequest(context=context, source_ids=['0', '1']))
    assert result['pairs'] == []


@pytest.mark.asyncio
async def test_explicit_native_snapshot_is_compared_with_each_selected_source():
    from app.services.context_review import ContextReviewRequest, NativeSnapshot, prepare_review
    sources = [{'source_id': key, 'source_type': 'prompt', 'revision': key, 'content': content, 'owner_agent_id': None, 'enabled': True, 'policy': ContextPolicy(scope='global').model_dump()} for key, content in [('a', 'Require approval.'), ('b', 'Proceed autonomously.')]]
    request = ContextReviewRequest(context=CanonicalContextDeliveryRequest(consumer_surface='codex'), source_ids=['a', 'b'], native_snapshots=[NativeSnapshot(name='visible', content='Ask beforehand.', revision='supplied-v1', surface='codex')])
    with patch('app.services.context_review.inventory', new=AsyncMock(return_value={'sources': sources})):
        result = await prepare_review(AsyncMock(), request)
    assert result['pairs'] == [['a', 'b'], ['a', 'native:visible'], ['b', 'native:visible']]
