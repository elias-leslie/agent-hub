"""Phase 3.6 E2E tests for ``complete_internal``.

Drives the new ``app.llm`` stack end-to-end through the faux provider so
the flag flip in Phase 3.6 has a green baseline that exercises:

* the session_repo collapse (mocked DB; we verify the wiring, not the
  DB upserts which are covered separately in ``test_request_setup.py``);
* the memory injection bypass when ``use_memory=False``;
* the out-of-band citation extractor (D9 — returns [] when use_memory
  is False, never touches the assistant message content);
* the ``CompletionInternalResult`` shape matched by the downstream
  contract documented in ``downstream-consumers.md`` Section 6.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.api.complete.core import complete_internal
from app.api.complete.types import CompletionInternalResult
from app.llm.providers.faux import (
    faux_assistant_message,
    faux_thinking,
    faux_tool_call,
    register_faux_provider,
)
from app.llm.types import TextContent


@pytest.mark.asyncio
async def test_new_pipeline_single_turn_text_response() -> None:
    """Single-turn text path returns the assistant text in CompletionInternalResult."""
    reg = register_faux_provider()
    try:
        reg.set_responses([faux_assistant_message("hello world")])
        model = reg.get_model()
        assert model is not None

        db = AsyncMock()
        fake_session = SimpleNamespace(id="sess-baseline")

        with (
            patch(
                "app.api.complete.core.setup_completion_session",
                new=AsyncMock(
                    return_value=(
                        fake_session,
                        "sess-baseline",
                        True,
                        [{"role": "user", "content": "hi"}],
                    )
                ),
            ),
            patch(
                "app.api.complete.core.resolve_llm_model",
                return_value=model,
            ),
        ):
            result = await complete_internal(
                temperature=0.0,
                messages=[{"role": "user", "content": "hi"}],
                model=model.id,
                provider=model.provider,
                project_id="agent-hub",
                db=db,
                use_memory=False,
            )

        assert isinstance(result, CompletionInternalResult)
        assert result.content == "hello world"
        assert result.session_id == "sess-baseline"
        assert result.finish_reason == "stop"
        assert result.turns == 1
        assert result.tool_calls_count == 0
        assert result.model == model.id
        assert result.provider == model.provider
        # Usage fields propagate from the AssistantMessage.usage shape.
        assert result.input_tokens >= 0
        assert result.output_tokens >= 0
    finally:
        reg.unregister()


@pytest.mark.asyncio
async def test_new_pipeline_skips_memory_injection_when_use_memory_false() -> None:
    """``use_memory=False`` must not call inject_memory_context at all."""
    reg = register_faux_provider()
    try:
        reg.set_responses([faux_assistant_message("ack")])
        model = reg.get_model()
        assert model is not None

        inject_mock = AsyncMock()
        with (
            patch(
                "app.api.complete.core.setup_completion_session",
                new=AsyncMock(
                    return_value=(
                        SimpleNamespace(id="sess-no-mem"),
                        "sess-no-mem",
                        True,
                        [{"role": "user", "content": "hi"}],
                    )
                ),
            ),
            patch(
                "app.api.complete.core.resolve_llm_model",
                return_value=model,
            ),
            patch(
                "app.api.complete.core.inject_memory_context",
                new=inject_mock,
            ),
        ):
            result = await complete_internal(
                temperature=0.0,
                messages=[{"role": "user", "content": "hi"}],
                model=model.id,
                provider=model.provider,
                project_id="agent-hub",
                db=AsyncMock(),
                use_memory=False,
            )

        inject_mock.assert_not_awaited()
        assert result.memory_uuids == []
        assert result.cited_uuids == []
    finally:
        reg.unregister()


@pytest.mark.asyncio
async def test_new_pipeline_citation_extractor_returns_empty_without_memory() -> None:
    """D9 — citation extraction is out-of-band and skipped when memory off."""
    reg = register_faux_provider()
    try:
        reg.set_responses([faux_assistant_message("ack")])
        model = reg.get_model()
        assert model is not None

        extract_mock = AsyncMock(return_value=["should-not-be-called"])
        with (
            patch(
                "app.api.complete.core.setup_completion_session",
                new=AsyncMock(
                    return_value=(
                        SimpleNamespace(id="sess-cite-off"),
                        "sess-cite-off",
                        True,
                        [{"role": "user", "content": "hi"}],
                    )
                ),
            ),
            patch(
                "app.api.complete.core.resolve_llm_model",
                return_value=model,
            ),
            patch(
                "app.api.complete.core.extract_cited_uuids",
                new=extract_mock,
            ),
        ):
            result = await complete_internal(
                temperature=0.0,
                messages=[{"role": "user", "content": "hi"}],
                model=model.id,
                provider=model.provider,
                project_id="agent-hub",
                db=AsyncMock(),
                use_memory=False,
            )

        extract_mock.assert_not_awaited()
        assert result.cited_uuids == []
    finally:
        reg.unregister()


@pytest.mark.asyncio
async def test_new_pipeline_invokes_memory_and_citation_when_use_memory_true() -> None:
    """``use_memory=True`` injects memory and post-processes citations."""
    reg = register_faux_provider()
    try:
        reg.set_responses([faux_assistant_message("ack with ref ab12")])
        model = reg.get_model()
        assert model is not None

        injected_msgs = [{"role": "user", "content": "hi with memory"}]
        inject_mock = AsyncMock(return_value=(injected_msgs, ["uuid-a", "uuid-b"], 2))
        extract_mock = AsyncMock(return_value=["uuid-a"])

        with (
            patch(
                "app.api.complete.core.setup_completion_session",
                new=AsyncMock(
                    return_value=(
                        SimpleNamespace(id="sess-mem"),
                        "sess-mem",
                        True,
                        [{"role": "user", "content": "hi"}],
                    )
                ),
            ),
            patch(
                "app.api.complete.core.resolve_llm_model",
                return_value=model,
            ),
            patch(
                "app.api.complete.core.inject_memory_context",
                new=inject_mock,
            ),
            patch(
                "app.api.complete.core.extract_cited_uuids",
                new=extract_mock,
            ),
        ):
            result = await complete_internal(
                temperature=0.0,
                messages=[{"role": "user", "content": "hi"}],
                model=model.id,
                provider=model.provider,
                project_id="agent-hub",
                db=AsyncMock(),
                use_memory=True,
                memory_group_id="project:agent-hub",
            )

        inject_mock.assert_awaited_once()
        extract_mock.assert_awaited_once()
        assert result.memory_uuids == ["uuid-a", "uuid-b"]
        assert result.cited_uuids == ["uuid-a"]
    finally:
        reg.unregister()


@pytest.mark.asyncio
async def test_new_pipeline_propagates_thinking_content() -> None:
    """Thinking blocks land in ``thinking_content`` + ``thinking_tokens``."""
    reg = register_faux_provider()
    try:
        reg.set_responses(
            [
                faux_assistant_message(
                    [
                        faux_thinking("plan: greet"),
                        TextContent(text="hello"),
                    ]
                )
            ]
        )
        model = reg.get_model()
        assert model is not None

        with (
            patch(
                "app.api.complete.core.setup_completion_session",
                new=AsyncMock(
                    return_value=(
                        SimpleNamespace(id="sess-think"),
                        "sess-think",
                        True,
                        [{"role": "user", "content": "hi"}],
                    )
                ),
            ),
            patch(
                "app.api.complete.core.resolve_llm_model",
                return_value=model,
            ),
        ):
            result = await complete_internal(
                temperature=0.0,
                messages=[{"role": "user", "content": "hi"}],
                model=model.id,
                provider=model.provider,
                project_id="agent-hub",
                db=AsyncMock(),
                use_memory=False,
            )

        assert result.content == "hello"
        assert result.thinking_content == "plan: greet"
        assert result.thinking_tokens is not None and result.thinking_tokens > 0
    finally:
        reg.unregister()


@pytest.mark.asyncio
async def test_new_pipeline_strips_tagged_thinking_from_text_content() -> None:
    """OpenAI-compatible providers may emit raw ``</think>`` text."""
    reg = register_faux_provider()
    try:
        reg.set_responses(
            [
                faux_assistant_message(
                    "plan: answer tersely</think>final answer",
                )
            ]
        )
        model = reg.get_model()
        assert model is not None

        with patch(
            "app.api.complete.core.resolve_llm_model",
            return_value=model,
        ):
            result = await complete_internal(
                temperature=0.0,
                messages=[{"role": "user", "content": "hi"}],
                model=model.id,
                provider=model.provider,
                project_id="agent-hub",
                db=None,
                use_memory=False,
            )

        assert result.content == "final answer"
        assert result.thinking_content == "plan: answer tersely"
    finally:
        reg.unregister()


@pytest.mark.asyncio
async def test_new_pipeline_trims_visible_content_after_tagged_thinking() -> None:
    """Tagged thinking removal should not leak separator whitespace into content."""
    reg = register_faux_provider()
    try:
        reg.set_responses(
            [
                faux_assistant_message(
                    "plan: answer exactly</think>\n\nexact answer\n",
                )
            ]
        )
        model = reg.get_model()
        assert model is not None

        with patch(
            "app.api.complete.core.resolve_llm_model",
            return_value=model,
        ):
            result = await complete_internal(
                temperature=0.0,
                messages=[{"role": "user", "content": "hi"}],
                model=model.id,
                provider=model.provider,
                project_id="agent-hub",
                db=None,
                use_memory=False,
            )

        assert result.content == "exact answer"
        assert result.thinking_content == "plan: answer exactly"
    finally:
        reg.unregister()


@pytest.mark.asyncio
async def test_new_pipeline_execute_tools_drives_unified_tool_loop() -> None:
    """``execute_tools=True`` runs the unified tool loop via app.services.tools.

    The faux provider scripts one ``toolUse``-stop turn + a final ``stop``
    turn. We patch ``create_direct_handler`` so the runner returns a known
    payload — the wiring is what we're verifying, not the real handler.
    """
    reg = register_faux_provider()
    try:
        reg.set_responses(
            [
                faux_assistant_message(
                    [faux_tool_call("echo", {"text": "hi"}, id="call-1")],
                    stop_reason="toolUse",
                ),
                faux_assistant_message("acknowledged"),
            ]
        )
        model = reg.get_model()
        assert model is not None

        class _StubHandler:
            async def execute(self, call: Any) -> Any:
                from app.services.tools.base import ToolResult

                return ToolResult(
                    tool_use_id=call.id,
                    content=f"echoed: {call.input.get('text', '')}",
                    is_error=False,
                    duration_ms=1,
                )

        with (
            patch(
                "app.api.complete.core.setup_completion_session",
                new=AsyncMock(
                    return_value=(
                        SimpleNamespace(id="sess-tools"),
                        "sess-tools",
                        True,
                        [{"role": "user", "content": "run echo"}],
                    )
                ),
            ),
            patch(
                "app.api.complete.core.resolve_llm_model",
                return_value=model,
            ),
            patch(
                "app.api.complete.core.create_direct_handler",
                return_value=_StubHandler(),
            ),
        ):
            result = await complete_internal(
                temperature=0.0,
                messages=[{"role": "user", "content": "run echo"}],
                model=model.id,
                provider=model.provider,
                project_id="agent-hub",
                db=AsyncMock(),
                use_memory=False,
                execute_tools=True,
                max_turns=4,
            )

        assert result.tool_calls_count == 1
        assert result.turns >= 2
        assert result.finish_reason == "stop"
        assert result.content == "acknowledged"
    finally:
        reg.unregister()


@pytest.mark.asyncio
async def test_new_pipeline_result_shape_matches_downstream_contract() -> None:
    """All fields downstream consumers read on a successful turn must be set.

    Cross-reference: ``downstream-consumers.md`` Section 6 — every key in
    the SSE ``done`` event + non-streaming ``CompletionResponse`` is built
    from ``CompletionInternalResult``. The wire response builder lives
    outside this function, but it cannot synthesize fields we never set.
    """
    reg = register_faux_provider()
    try:
        reg.set_responses([faux_assistant_message("done")])
        model = reg.get_model()
        assert model is not None

        with (
            patch(
                "app.api.complete.core.setup_completion_session",
                new=AsyncMock(
                    return_value=(
                        SimpleNamespace(id="sess-shape"),
                        "sess-shape",
                        True,
                        [{"role": "user", "content": "hi"}],
                    )
                ),
            ),
            patch(
                "app.api.complete.core.resolve_llm_model",
                return_value=model,
            ),
        ):
            result = await complete_internal(
                temperature=0.0,
                messages=[{"role": "user", "content": "hi"}],
                model="claude-sonnet-4-6",
                provider="anthropic",
                project_id="agent-hub",
                db=AsyncMock(),
                use_memory=False,
                requested_model="claude-sonnet-4-6",
                requested_provider="anthropic",
            )

        # Required by downstream-consumers.md Section 6:
        assert result.content == "done"
        assert result.model == "claude-sonnet-4-6"
        assert result.provider == "anthropic"
        assert isinstance(result.input_tokens, int)
        assert isinstance(result.output_tokens, int)
        assert result.finish_reason == "stop"
        assert result.session_id == "sess-shape"
        assert result.memory_uuids == []
        assert result.cited_uuids == []
        assert result.turns == 1
        assert result.tool_calls_count == 0
        assert result.model_used == "claude-sonnet-4-6"
        assert result.requested_model == "claude-sonnet-4-6"
        assert result.requested_provider == "anthropic"
    finally:
        reg.unregister()
