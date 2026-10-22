"""OpenCode snapshots retain native evidence without promoting selection to execution."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.services.session_ingestion.opencode_sync import (
    NativeExport,
    NativeMessage,
    normalize_messages,
    sync_opencode_export,
)


def export() -> dict:
    return {'info': {'id': 'ses_fixture', 'model': {'providerID': 'opencode', 'id': 'glm-5.3-flash-free'},
                     'location': {'directory': '/projects/agent-hub'}},
            'messages': [{'id': 'msg_user', 'type': 'user', 'time': {'created': 1000}, 'text': 'hello'},
                         {'id': 'msg_response', 'type': 'assistant', 'time': {'created': 1001, 'completed': 2000},
                          'model': {'providerID': 'opencode', 'id': 'glm-5.3-flash-free'},
                          'content': [{'type': 'text', 'text': 'done'}],
                          'tokens': {'input': 10, 'output': 2, 'cache': {'read': 8, 'write': 1}}, 'cost': 0}]}


def test_native_usage_and_stable_event_identity():
    payload = NativeExport.model_validate(export())
    first = normalize_messages(payload.messages)
    assert first == normalize_messages(payload.messages)
    assert [event.event_type for event in first] == ['user_message', 'assistant_message', 'usage']
    assert first[-1].model_used == 'opencode/glm-5.3-flash-free'
    assert first[-1].usage == {'scope': 'response', 'source': 'opencode.session.message',
        'response_id': 'msg_response', 'input_tokens': 19, 'output_tokens': 2,
        'cached_input_tokens': 8, 'cache_write_tokens': 1,
        'native': {'tokens': {'input': 10, 'output': 2, 'cache': {'read': 8, 'write': 1}}, 'cost': 0}, 'cost_usd': 0}


def test_partial_responses_do_not_commit_text_or_usage_and_errors_have_no_model_claim():
    message = NativeMessage(id='msg_error', type='assistant', model={'providerID': 'opencode', 'id': 'glm-5.3-flash-free'},
                            content=[{'type': 'text', 'text': 'unfinished'}], tokens={'input': 10},
                            error={'message': '403 rejected'})
    events = normalize_messages([message])
    assert len(events) == 1 and events[0].event_type == 'error'
    assert events[0].model_used is None


def test_malformed_native_identity_is_rejected():
    payload = export()
    payload['info']['id'] = '../other'
    with pytest.raises(ValidationError):
        NativeExport.model_validate(payload)


@pytest.mark.asyncio
async def test_sync_preserves_aico_correlation_and_uses_canonical_ingestion(monkeypatch):
    module = 'app.services.session_ingestion.opencode_sync'
    existing = MagicMock(id='ses_fixture', model='opencode/unknown', provider_metadata={
        'harness': 'opencode', 'aico_session_id': 'aico-widget-12345678'})
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = existing
    db.execute.return_value = result
    monkeypatch.setattr(module + '._resolve_canonical_project_id', AsyncMock(return_value='agent-hub'))
    upsert = AsyncMock(return_value=(existing, None))
    append = AsyncMock(return_value=MagicMock(events_appended=3, events_skipped=0))
    heartbeat = AsyncMock()
    monkeypatch.setattr(module + '.upsert_session', upsert)
    monkeypatch.setattr(module + '.append_normalized_events', append)
    monkeypatch.setattr(module + '.heartbeat_session', heartbeat)
    assert (await sync_opencode_export(db, export()))['events_appended'] == 3
    request = upsert.call_args.args[1]
    assert request.model == 'opencode/glm-5.3-flash-free'
    assert request.provider_metadata['aico_session_id'] == 'aico-widget-12345678'
    assert request.provider_metadata['opencode_selection']['id'] == 'glm-5.3-flash-free'
    assert append.call_args.args[2].events[-1].usage['cost_usd'] == 0


@pytest.mark.asyncio
async def test_sync_refuses_foreign_sessions_and_unknown_projects(monkeypatch):
    module = 'app.services.session_ingestion.opencode_sync'
    db = AsyncMock()
    monkeypatch.setattr(module + '._resolve_canonical_project_id', AsyncMock(return_value=None))
    with pytest.raises(ValueError, match='outside registered'):
        await sync_opencode_export(db, export())
    result = MagicMock()
    result.scalar_one_or_none.return_value = MagicMock(provider_metadata={'harness': 'pi'})
    db.execute.return_value = result
    monkeypatch.setattr(module + '._resolve_canonical_project_id', AsyncMock(return_value='agent-hub'))
    with pytest.raises(ValueError, match='another native session'):
        await sync_opencode_export(db, export())


@pytest.mark.asyncio
async def test_child_export_does_not_double_count_inherited_history():
    payload = export()
    payload['info']['parentID'] = 'ses_parent'
    with pytest.raises(ValueError, match='child and fork accounting'):
        await sync_opencode_export(AsyncMock(), payload)
