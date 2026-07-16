"""Phase 3.6 E2E tests for ``complete_internal``.

Drives the new ``app.llm`` stack end-to-end through the faux provider so
the flag flip in Phase 3.6 has a green baseline that exercises:

* the session_repo collapse (mocked DB; we verify the wiring, not the
  DB upserts which are covered separately in ``test_request_setup.py``);
* canonical prompt injection with optional memories disabled;
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
from app.services.agent_routing_utils import inject_agent_mandates
from app.services.llm_errors import ProviderError
from app.services.memory.context_injector_ops import inject_memory_block
from app.services.memory.context_resilience import CanonicalContextInjectionFailed
from app.services.owned_prompt_service import AGENT_SYSTEM_PROMPT_TYPE


def _verified_context(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return inject_memory_block(messages, "## Safety Directive\nTest canonical context")


@pytest.fixture(autouse=True)
def _stub_canonical_context_injection():
    """Keep pipeline unit tests focused on completion behavior, not DB context IO."""
    inject_mock = AsyncMock(
        side_effect=lambda messages, *_args, **_kwargs: (
            _verified_context(messages),
            [],
            0,
        )
    )
    with patch("app.api.complete.core.inject_memory_context", new=inject_mock):
        yield


@pytest.mark.asyncio
async def test_reference_only_provider_is_rejected_before_execution() -> None:
    with pytest.raises(ProviderError) as exc_info:
        await complete_internal(
            temperature=0.0,
            messages=[{"role": "user", "content": "hi"}],
            model="claude-sonnet-4-6",
            provider="claude",
            project_id="agent-hub",
            db=None,
            use_memory=False,
        )

    assert exc_info.value.status_code == 400
    assert "catalog references" in str(exc_info.value)


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
async def test_new_pipeline_surfaces_provider_error_details() -> None:
    """Provider terminal errors must not collapse into an unexplained empty response."""
    reg = register_faux_provider()
    try:
        reg.set_responses(
            [
                faux_assistant_message(
                    [],
                    stop_reason="error",
                    error_message="429 Too Many Requests: project quota exhausted",
                )
            ]
        )
        model = reg.get_model()
        assert model is not None

        with patch("app.api.complete.core.resolve_llm_model", return_value=model):
            result = await complete_internal(
                temperature=0.0,
                messages=[{"role": "user", "content": "hi"}],
                model=model.id,
                provider=model.provider,
                project_id="agent-hub",
                db=None,
                use_memory=False,
            )

        assert result.content == ""
        assert result.finish_reason == "error"
        assert result.status == "error"
        assert result.error == "429 Too Many Requests: project quota exhausted"
        assert result.error_summary == {
            "count": 3,
            "items": [
                {
                    "kind": "execution_error",
                    "message": "429 Too Many Requests: project quota exhausted",
                },
                {"kind": "execution_status", "message": "error"},
                {"kind": "finish_reason", "message": "error"},
            ],
        }
    finally:
        reg.unregister()


@pytest.mark.asyncio
async def test_new_pipeline_injects_prompts_without_optional_memories() -> None:
    """``use_memory=False`` still delivers canonical operator prompts."""
    reg = register_faux_provider()
    try:
        reg.set_responses([faux_assistant_message("ack")])
        model = reg.get_model()
        assert model is not None

        inject_mock = AsyncMock(
            return_value=(
                _verified_context([{"role": "user", "content": "hi"}]),
                [],
                0,
            )
        )
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

        inject_mock.assert_awaited_once()
        inject_args = inject_mock.await_args
        assert inject_args is not None
        assert inject_args.kwargs["project_id"] == "agent-hub"
        assert inject_args.kwargs["include_memories"] is False
        assert inject_args.kwargs["consumer_surface"] == "agent_runtime"
        assert result.memory_uuids == []
        assert result.cited_uuids == []
    finally:
        reg.unregister()


@pytest.mark.asyncio
async def test_context_failure_aborts_before_model_call() -> None:
    reg = register_faux_provider()
    try:
        model = reg.get_model()
        assert model is not None
        run_model = AsyncMock()
        with (
            patch(
                "app.api.complete.core.setup_completion_session",
                new=AsyncMock(
                    return_value=(
                        SimpleNamespace(id="sess-context-failed"),
                        "sess-context-failed",
                        True,
                        [{"role": "user", "content": "hi"}],
                    )
                ),
            ),
            patch(
                "app.api.complete.core.inject_memory_context",
                new=AsyncMock(
                    side_effect=CanonicalContextInjectionFailed(
                        "required canonical context unavailable"
                    )
                ),
            ),
            patch("app.api.complete.core.run_completion", new=run_model),
            pytest.raises(
                CanonicalContextInjectionFailed,
                match="required canonical context unavailable",
            ),
        ):
            await complete_internal(
                temperature=0.0,
                messages=[{"role": "user", "content": "hi"}],
                model=model.id,
                provider=model.provider,
                project_id="agent-hub",
                db=AsyncMock(),
                use_memory=False,
            )

        run_model.assert_not_awaited()
    finally:
        reg.unregister()


@pytest.mark.asyncio
async def test_ephemeral_completion_still_loads_canonical_context() -> None:
    """db=None keeps ephemeral persistence, not a context-injection bypass."""
    reg = register_faux_provider()
    try:
        reg.set_responses([faux_assistant_message("ack")])
        model = reg.get_model()
        assert model is not None
        inject_mock = AsyncMock(
            return_value=(
                _verified_context([{"role": "user", "content": "hi"}]),
                [],
                0,
            )
        )
        with (
            patch("app.api.complete.core.resolve_llm_model", return_value=model),
            patch("app.api.complete.core.inject_memory_context", new=inject_mock),
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

        inject_mock.assert_awaited_once()
        assert inject_mock.await_args is not None
        assert inject_mock.await_args.args[1] is None
        assert result.session_id.startswith("ephemeral:")
    finally:
        reg.unregister()


@pytest.mark.asyncio
async def test_persona_owned_prompt_and_row_context_reach_provider_exactly_once() -> None:
    """Canonical prepending must not duplicate the agent-specific prompt layer."""
    from app.workflows._heartbeat_steps import _invoke_complete_internal

    owned_prompt_marker = "DISTINCT_OWNED_PERSONA_SYSTEM_PROMPT"
    persona_row_marker = "DISTINCT_NATIVE_PERSONA_ROW_CONTEXT"
    canonical_marker = "DISTINCT_CANONICAL_OPERATOR_CONTEXT"
    agent = SimpleNamespace(
        id=9,
        slug="persona",
        name="Jenny",
        system_prompt="STALE_AGENT_SYSTEM_PROMPT_MIRROR",
    )
    assignment = SimpleNamespace(
        role="system",
        priority=0,
        prompt=SimpleNamespace(
            enabled=True,
            is_global=False,
            prompt_type=AGENT_SYSTEM_PROMPT_TYPE,
            name="Persona System Prompt",
            slug="persona-system-prompt",
            content=f"<agent_persona>{owned_prompt_marker}</agent_persona>",
            updated_at=None,
        ),
    )
    with (
        patch(
            "app.services.runtime_prompt_stack.get_agent_prompts",
            new=AsyncMock(return_value=[assignment]),
        ),
        patch(
            "app.services.persona_service.get_persona_context_for_agent",
            new=AsyncMock(return_value=persona_row_marker),
        ),
    ):
        mandate = await inject_agent_mandates(
            agent,
            AsyncMock(),
            task_type="heartbeat",
        )

    assert mandate.system_content.count(owned_prompt_marker) == 1
    assert mandate.system_content.count(persona_row_marker) == 1
    assert "STALE_AGENT_SYSTEM_PROMPT_MIRROR" not in mandate.system_content

    captured: dict[str, str] = {}

    def capture_context(context, *_args):
        captured["system_prompt"] = context.system_prompt or ""
        return faux_assistant_message("ack")

    reg = register_faux_provider()
    try:
        reg.set_responses([capture_context])
        model = reg.get_model()
        assert model is not None
        inject_mock = AsyncMock(
            side_effect=lambda messages, *_args, **_kwargs: (
                inject_memory_block(messages, canonical_marker),
                [],
                0,
            )
        )
        with (
            patch("app.api.complete.core.resolve_llm_model", return_value=model),
            patch("app.api.complete.core.inject_memory_context", new=inject_mock),
        ):
            result = await _invoke_complete_internal(
                None,
                messages=[
                    {"role": "system", "content": mandate.system_content},
                    {"role": "user", "content": "heartbeat"},
                ],
                model=model.id,
                provider=model.provider,
                temperature=0.0,
                execution_project="agent-hub",
                heartbeat_session_id="heartbeat:exact-once",
                memory_config=None,
                max_turns=1,
                thinking_level=None,
                working_dir=None,
            )

        assert result.content == "ack"
        provider_system_prompt = captured["system_prompt"]
        assert provider_system_prompt.count(canonical_marker) == 1
        assert provider_system_prompt.count(owned_prompt_marker) == 1
        assert provider_system_prompt.count(persona_row_marker) == 1
        assert provider_system_prompt.count("<agent-hub-context ") == 1
    finally:
        reg.unregister()


@pytest.mark.asyncio
async def test_preinjected_bypass_requires_verified_canonical_envelope() -> None:
    """A marker cannot suppress injection unless its payload hash verifies."""
    reg = register_faux_provider()
    try:
        model = reg.get_model()
        assert model is not None
        run_model = AsyncMock()
        with (
            patch("app.api.complete.core.run_completion", new=run_model),
            pytest.raises(
                CanonicalContextInjectionFailed,
                match="hash-verified Agent Hub canonical context envelope",
            ),
        ):
            await complete_internal(
                temperature=0.0,
                messages=[
                    {"role": "system", "content": "unverified agent prompt"},
                    {"role": "user", "content": "hi"},
                ],
                model=model.id,
                provider=model.provider,
                project_id="agent-hub",
                db=None,
                canonical_context_preinjected=True,
            )

        run_model.assert_not_awaited()
    finally:
        reg.unregister()


@pytest.mark.asyncio
async def test_unverified_injector_output_aborts_before_model_call() -> None:
    """A nominally successful injector cannot pass raw, unproven messages."""
    reg = register_faux_provider()
    try:
        model = reg.get_model()
        assert model is not None
        run_model = AsyncMock()
        with (
            patch(
                "app.api.complete.core.inject_memory_context",
                new=AsyncMock(
                    return_value=([{"role": "user", "content": "hi"}], [], 0)
                ),
            ),
            patch("app.api.complete.core.run_completion", new=run_model),
            pytest.raises(
                CanonicalContextInjectionFailed,
                match="did not return a hash-verified Agent Hub canonical context envelope",
            ),
        ):
            await complete_internal(
                temperature=0.0,
                messages=[{"role": "user", "content": "hi"}],
                model=model.id,
                provider=model.provider,
                project_id="agent-hub",
                db=None,
            )

        run_model.assert_not_awaited()
    finally:
        reg.unregister()


@pytest.mark.asyncio
async def test_verified_preinjected_context_skips_only_duplicate_injection() -> None:
    reg = register_faux_provider()
    try:
        reg.set_responses([faux_assistant_message("ack")])
        model = reg.get_model()
        assert model is not None
        inject_mock = AsyncMock()
        messages = _verified_context([{"role": "user", "content": "hi"}])
        with (
            patch("app.api.complete.core.resolve_llm_model", return_value=model),
            patch("app.api.complete.core.inject_memory_context", new=inject_mock),
        ):
            result = await complete_internal(
                temperature=0.0,
                messages=messages,
                model=model.id,
                provider=model.provider,
                project_id="agent-hub",
                db=None,
                canonical_context_preinjected=True,
            )

        inject_mock.assert_not_awaited()
        assert result.content == "ack"
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

        injected_msgs = _verified_context(
            [{"role": "user", "content": "hi with memory"}]
        )
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
async def test_new_pipeline_trims_text_when_structured_thinking_is_present() -> None:
    """Some providers split thinking into blocks but keep separator whitespace."""
    reg = register_faux_provider()
    try:
        reg.set_responses(
            [
                faux_assistant_message(
                    [
                        faux_thinking("plan: answer exactly"),
                        TextContent(text="\n\nexact answer\n"),
                    ]
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
                "app.api.complete.tool_provisioner.create_direct_handler",
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
async def test_new_pipeline_passes_tool_definitions_to_unified_context() -> None:
    """Agentic completion must expose provisioned tools as native model tools."""
    reg = register_faux_provider()
    try:
        def assert_tool_context(context: Any, *_args: Any) -> Any:
            assert context.tools is not None
            assert len(context.tools) == 1
            tool = context.tools[0]
            assert tool.name == "echo"
            assert tool.description == "Echo text"
            assert tool.parameters == {
                "type": "object",
                "properties": {"text": {"type": "string"}},
            }
            return faux_assistant_message("tool schema visible")

        reg.set_responses([assert_tool_context])
        model = reg.get_model()
        assert model is not None

        with patch(
            "app.api.complete.core.resolve_llm_model",
            return_value=model,
        ):
            result = await complete_internal(
                temperature=0.0,
                messages=[{"role": "user", "content": "run echo"}],
                model=model.id,
                provider=model.provider,
                project_id="agent-hub",
                db=None,
                use_memory=False,
                execute_tools=True,
                max_turns=1,
                tools=[
                    {
                        "name": "echo",
                        "description": "Echo text",
                        "input_schema": {
                            "type": "object",
                            "properties": {"text": {"type": "string"}},
                        },
                    }
                ],
            )

        assert result.finish_reason == "stop"
        assert result.content == "tool schema visible"
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
                model=model.id,
                provider=model.provider,
                project_id="agent-hub",
                db=AsyncMock(),
                use_memory=False,
                requested_model="codex/gpt-5.4-mini",
                requested_provider="codex",
            )

        # Required by downstream-consumers.md Section 6:
        assert result.content == "done"
        assert result.model == "codex/gpt-5.4-mini"
        assert result.provider == "codex"
        assert isinstance(result.input_tokens, int)
        assert isinstance(result.output_tokens, int)
        assert result.finish_reason == "stop"
        assert result.session_id == "sess-shape"
        assert result.memory_uuids == []
        assert result.cited_uuids == []
        assert result.turns == 1
        assert result.tool_calls_count == 0
        assert result.model_used == model.id
        assert result.requested_model == "codex/gpt-5.4-mini"
        assert result.requested_provider == "codex"
    finally:
        reg.unregister()
