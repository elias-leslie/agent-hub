"""Cross-client regressions for explicit routing and failed completions."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.api.complete.orchestration_helpers import execute_and_respond
from app.api.complete.schemas import CompletionRequest
from app.api.complete.types import CompletionInternalResult
from app.routing.resolution import apply_mention_override


def test_explicit_sdk_model_is_honored_without_prompt_directives():
    request = CompletionRequest(agent_slug="chat", project_id="portfolio-ai", model="gemini-3.8-flash", messages=[{"role": "user", "content": "hello"}])
    model, provider = apply_mention_override(request, "gemini-3.1-flash-lite-preview")
    assert model == "gemini-3.8-flash"
    assert provider == "gemini"
    assert request.messages[0].content == "hello"


def test_unknown_explicit_model_is_rejected():
    request = CompletionRequest(agent_slug="chat", project_id="portfolio-ai", model="nonexistent-model", messages=[{"role": "user", "content": "hello"}])
    with pytest.raises(HTTPException, match="Unknown model"):
        apply_mention_override(request, "gemini-3.8-flash")


def test_conflicting_model_directives_are_rejected():
    request = CompletionRequest(agent_slug="chat", project_id="portfolio-ai", model="gemini-3.8-flash", messages=[{"role": "user", "content": "@codex/gpt-5.5 hello"}])
    with pytest.raises(HTTPException, match="Conflicting"):
        apply_mention_override(request, "gemini-3.8-flash")


@pytest.mark.asyncio
@pytest.mark.parametrize("finish_reason,content,detail", [
    ("error", "", "Provider returned finish_reason=error"),
    ("aborted", "partial", "Provider returned finish_reason=aborted"),
    ("stop", "invalid JSON", "Model output does not match JSON schema"),
])
async def test_failed_result_is_recorded_and_never_finalized_as_success(finish_reason, content, detail):
    request = CompletionRequest(agent_slug="chat", project_id="portfolio-ai", messages=[{"role": "user", "content": "synthetic"}], response_format={"type": "json_object", "schema": {"type": "object"}})
    result = CompletionInternalResult(content=content, model="gemini-3.8-flash", provider="gemini", finish_reason=finish_reason)
    with (
        patch("app.api.complete.orchestration_helpers.execute_completion", new=AsyncMock(return_value=(result, result.model, False, [], "synthetic-session", None))),
        patch("app.api.complete.orchestration_helpers.process_completion_result", new_callable=AsyncMock) as finalize,
        patch("app.api.complete.error_handlers._notify_error", new_callable=AsyncMock) as notify,
        pytest.raises(HTTPException) as raised,
    ):
        await execute_and_respond(request, result.model, result.provider, None, [], [], False, AsyncMock(), SimpleNamespace(), "synthetic-session", None, None, True, None, 0, [], "chat", True)
    assert raised.value.status_code == 502
    assert detail in str(raised.value.detail)
    finalize.assert_not_awaited()
    notify.assert_awaited_once()


def test_sync_and_streaming_preserve_sdk_prompt_and_json_contract():
    from app.api.complete.request_setup import build_message_list
    from app.api.complete.streaming_handlers import _build_streaming_messages
    request = CompletionRequest(agent_slug="chat", project_id="portfolio-ai", system_prompt="Use only supplied evidence.", messages=[{"role": "user", "content": "hello"}], response_format={"type": "json_object", "schema": {"type": "object", "required": ["answers"]}})
    sync, _ = build_message_list(request, [])
    streaming = _build_streaming_messages(request, [], None)
    for messages in (sync, streaming):
        system = "\n".join(m.content for m in messages if m.role == "system" and isinstance(m.content, str))
        assert "Use only supplied evidence." in system
        assert '"answers"' in system
        assert "JSON" in system


def test_context_preserves_all_system_layers_and_assistant_history():
    from app.api.complete.orchestrator import build_context_from_messages
    from app.llm.types import AssistantMessage
    context = build_context_from_messages([
        {"role": "system", "content": "Canonical operator instructions"},
        {"role": "system", "content": "App grounding instructions"},
        {"role": "user", "content": "Was it saved?"},
        {"role": "assistant", "content": "No. The save failed."},
        {"role": "user", "content": "What did you say?"},
    ])
    assert context.system_prompt is not None
    assert "App grounding instructions" in context.system_prompt
    assert "Canonical operator instructions" in context.system_prompt
    assert len(context.messages) == 3
    assert isinstance(context.messages[1], AssistantMessage)
    from app.llm.types import TextContent
    assert isinstance(context.messages[1].content[0], TextContent)
    assert context.messages[1].content[0].text == "No. The save failed."


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [429, 503])
async def test_provider_availability_status_is_preserved(status):
    from app.api.complete.orchestration_helpers import process_result
    from app.services.llm_errors import ProviderError
    result = CompletionInternalResult(content="", model="gemini-3.8-flash", provider="gemini", finish_reason="error", error=f"{status} Provider unavailable")
    request = CompletionRequest(agent_slug="chat", project_id="portfolio-ai", messages=[{"role": "user", "content": "test"}])
    with pytest.raises(ProviderError) as caught:
        await process_result(request, result, result.model, "test", None, None, True, [], None, 0, [], "chat", True, 0, None)
    assert caught.value.status_code == status


@pytest.mark.asyncio
async def test_failed_override_retains_effective_model_after_rollback():
    from app.api.complete.error_handlers import _store_error_event
    session = SimpleNamespace(status="active", health_detail=None)
    db = AsyncMock()
    db.get.return_value = session
    with (
        patch("app.services.event_storage.store_error_event", new_callable=AsyncMock),
        patch("app.api.complete.session_repo.apply_execution_metadata") as metadata,
        patch("app.api.complete.error_handlers.mark_session_terminal_state"),
    ):
        await _store_error_event(db, "test", "ProviderError", "503 unavailable", "chat", "gemini-3.8-flash")
    metadata.assert_called_once_with(session, requested_model="gemini-3.8-flash", effective_model="gemini-3.8-flash", fallback_used=False)
    assert session.status == "failed"
    db.commit.assert_awaited_once()
