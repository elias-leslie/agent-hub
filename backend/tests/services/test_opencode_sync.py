"""OpenCode snapshots retain native evidence without promoting selection to execution."""
from __future__ import annotations

import json
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


@pytest.mark.asyncio
async def test_retirement_is_exact_and_idempotent(monkeypatch):
    from app.services.session_ingestion import opencode_sync
    db = AsyncMock()
    session = MagicMock(id='ses_fixture', status='active')
    result = MagicMock()
    result.scalars.return_value.all.return_value = [session]
    db.execute.return_value = result
    native = AsyncMock(side_effect=[b'{}', b'{}', json.dumps(export()).encode()])
    monkeypatch.setattr(opencode_sync, '_native_command', native)
    async def sync(_db, payload, *, retired_by_tether=False):
        assert retired_by_tether
        assert payload['phase'] == 'shutdown'
        assert payload['aico_session_id'] == 'aico-widget-12345678'
        session.status = 'completed'
    monkeypatch.setattr(opencode_sync, 'sync_opencode_export', sync)
    first = await opencode_sync.retire_opencode_sessions(db, 'aico-widget-12345678')
    assert first['closed_session_ids'] == ['ses_fixture']
    assert native.call_args_list[0].args[:2] == ('api', 'session.interrupt')
    assert native.call_args_list[-1].args == ('session', 'export', 'ses_fixture')
    assert (await opencode_sync.retire_opencode_sessions(db, 'aico-widget-12345678'))['closed_session_ids'] == []
    assert native.call_count == 3
    with pytest.raises(ValueError, match='exact Tether'):
        await opencode_sync.retire_opencode_sessions(db, 'another-owner')


@pytest.mark.asyncio
async def test_retirement_refuses_a_different_native_export(monkeypatch):
    from app.services.session_ingestion import opencode_sync
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [MagicMock(id='ses_fixture', status='active')]
    db.execute.return_value = result
    monkeypatch.setattr(opencode_sync, '_native_command', AsyncMock(side_effect=[b'{}', b'{}', b'{"info":{"id":"ses_other"}}']))
    sync = AsyncMock()
    monkeypatch.setattr(opencode_sync, 'sync_opencode_export', sync)
    with pytest.raises(ValueError, match='identity differs'):
        await opencode_sync.retire_opencode_sessions(db, 'aico-widget-12345678')
    sync.assert_not_called()


def test_native_tool_content_and_duration_are_retained_without_rewriting_v1_events():
    message = NativeMessage(id='msg_tool', type='assistant', time={'created': 1000, 'completed': 2000},
        content=[{'type': 'tool', 'id': 'call', 'name': 'shell', 'state': {'status': 'completed',
                  'input': {'command': 'printf fixture'}, 'content': [{'type': 'text', 'text': 'fixture'}],
                  'metadata': {'exit': 0}}, 'time': {'ran': 1100, 'completed': 1200}}])
    result = normalize_messages([message])[-1]
    assert result.tool_output is not None
    assert result.tool_output['content'] == [{'type': 'text', 'text': 'fixture'}]
    assert result.duration_ms == 100
    assert normalize_messages([message], event_version=1)[-1].tool_output == {'output': None, 'error': None}


@pytest.mark.asyncio
async def test_late_idle_snapshot_cannot_reopen_a_retired_tether_conversation(monkeypatch):
    module = 'app.services.session_ingestion.opencode_sync'
    session = MagicMock(id='ses_fixture', model='opencode/glm-5.3-flash-free', provider_metadata={
        'harness': 'opencode', 'tether_retired': True, 'aico_session_id': 'aico-widget-12345678'})
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = session
    db.execute.return_value = result
    monkeypatch.setattr(module + '._resolve_canonical_project_id', AsyncMock(return_value='agent-hub'))
    monkeypatch.setattr(module + '.upsert_session', AsyncMock(return_value=(session, None)))
    monkeypatch.setattr(module + '.append_normalized_events', AsyncMock(return_value=MagicMock(events_appended=0, events_skipped=3)))
    heartbeat = AsyncMock()
    monkeypatch.setattr(module + '.heartbeat_session', heartbeat)
    await sync_opencode_export(db, export())
    assert heartbeat.call_args.args[2].status == 'completed'
    assert heartbeat.call_args.args[2].phase == 'shutdown'
