"""Tests for agent routing service."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.adapters.base import Message, ProviderError, RateLimitError
from app.constants.models import CLAUDE_HAIKU, CLAUDE_OPUS, CLAUDE_SONNET, GEMINI_FLASH
from app.services.agent_routing import (
    CompletionResult,
    MandateInjection,
    ResolvedAgent,
    complete_with_fallback,
    get_adapter,
    get_provider_for_model,
    inject_agent_mandates,
    inject_system_prompt_into_messages,
    resolve_agent,
)
from app.services.agent_service import AgentDTO
from app.services.prompt_service import get_runtime_excluded_prompt_roles


@dataclass
class _CapturedCall:
    kwargs: dict[str, object] | None = None


@pytest.fixture
def mock_agent() -> AgentDTO:
    from datetime import UTC, datetime

    return AgentDTO(
        id=1,
        slug="coder",
        name="Coder Agent",
        description="A coding assistant",
        system_prompt="You are a helpful coding assistant.",
        primary_model_id=CLAUDE_SONNET,
        fallback_models=[CLAUDE_HAIKU, GEMINI_FLASH],
        escalation_model_id=None,
        strategies={},
        temperature=0.7,
        thinking_level="low",
        verbosity_level=None,
        is_active=True,
        is_coding_agent=True,
        tool_permissions={},
        memory_config=None,
        max_concurrency=None,
        max_subagent_concurrency=None,
        daily_token_budget=None,
        hourly_request_limit=None,
        timeout_seconds=None,
        version=1,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.fixture
def mock_agent_no_fallbacks() -> AgentDTO:
    from datetime import UTC, datetime

    return AgentDTO(
        id=2,
        slug="simple",
        name="Simple Agent",
        description=None,
        system_prompt="Simple prompt.",
        primary_model_id=CLAUDE_HAIKU,
        fallback_models=[],
        escalation_model_id=None,
        strategies={},
        temperature=0.5,
        thinking_level=None,
        verbosity_level=None,
        is_active=True,
        is_coding_agent=False,
        tool_permissions=None,
        memory_config=None,
        max_concurrency=None,
        max_subagent_concurrency=None,
        daily_token_budget=None,
        hourly_request_limit=None,
        timeout_seconds=None,
        version=1,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


class TestGetProviderForModel:

    def test_claude_model(self) -> None:
        assert get_provider_for_model(CLAUDE_SONNET) == "claude"
        assert get_provider_for_model(CLAUDE_HAIKU) == "claude"
        assert get_provider_for_model(CLAUDE_OPUS) == "claude"

    def test_gemini_model(self) -> None:
        assert get_provider_for_model(GEMINI_FLASH) == "gemini"
        assert get_provider_for_model("gemini-3-pro") == "gemini"

    def test_unknown_defaults_to_claude(self) -> None:
        assert get_provider_for_model("unknown-model") == "claude"


class TestGetAdapter:

    def test_claude_adapter(self) -> None:
        from app.adapters.claude import ClaudeAdapter

        adapter = get_adapter("claude")
        assert isinstance(adapter, ClaudeAdapter)

    def test_gemini_adapter(self) -> None:
        from app.adapters.gemini import GeminiAdapter

        adapter = get_adapter("gemini")
        assert isinstance(adapter, GeminiAdapter)

    def test_unknown_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown provider"):
            get_adapter("unknown")


class TestResolveAgent:

    @pytest.mark.asyncio
    async def test_found_agent(self, mock_agent: AgentDTO) -> None:
        mock_db = AsyncMock()
        mock_service = MagicMock()
        mock_service.get_by_slug = AsyncMock(return_value=mock_agent)

        with patch("app.services.agent_routing_utils.get_agent_service", return_value=mock_service):
            result = await resolve_agent("coder", mock_db)

        assert isinstance(result, ResolvedAgent)
        assert result.agent == mock_agent
        assert result.model == CLAUDE_SONNET
        assert result.provider == "claude"
        mock_service.get_by_slug.assert_called_once_with(mock_db, "coder")

    @pytest.mark.asyncio
    async def test_agent_not_found(self) -> None:
        mock_db = AsyncMock()
        mock_service = MagicMock()
        mock_service.get_by_slug = AsyncMock(return_value=None)

        with (
            patch("app.services.agent_routing_utils.get_agent_service", return_value=mock_service),
            pytest.raises(HTTPException) as exc_info,
        ):
            await resolve_agent("unknown", mock_db)

        assert exc_info.value.status_code == 404
        assert "Agent 'unknown' not found" in str(exc_info.value.detail)


class TestInjectAgentMandates:

    @pytest.mark.asyncio
    async def test_returns_system_prompt(self, mock_agent: AgentDTO) -> None:
        result = await inject_agent_mandates(mock_agent)

        assert isinstance(result, MandateInjection)
        expected = "<agent_persona>\nYou are a helpful coding assistant.\n</agent_persona>"
        assert result.system_content == expected
        assert result.injected_uuids == []

    @pytest.mark.asyncio
    async def test_simple_agent(self, mock_agent_no_fallbacks: AgentDTO) -> None:
        result = await inject_agent_mandates(mock_agent_no_fallbacks)

        assert isinstance(result, MandateInjection)
        expected = "<agent_persona>\nSimple prompt.\n</agent_persona>"
        assert result.system_content == expected
        assert result.injected_uuids == []

    @pytest.mark.asyncio
    async def test_persona_runtime_excludes_prompt_backed_context_roles(self) -> None:
        from datetime import UTC, datetime

        persona_agent = AgentDTO(
            id=9,
            slug="persona",
            name="Persona",
            description=None,
            system_prompt="Legacy persona system prompt",
            primary_model_id=CLAUDE_SONNET,
            fallback_models=[],
            escalation_model_id=None,
            strategies={},
            temperature=0.3,
            thinking_level="medium",
            verbosity_level=None,
            is_active=True,
            is_coding_agent=False,
            tool_permissions=None,
            memory_config=None,
            max_concurrency=None,
            max_subagent_concurrency=None,
            daily_token_budget=None,
            hourly_request_limit=None,
            timeout_seconds=None,
            version=1,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        mock_db = AsyncMock()
        with (
            patch(
                "app.services.prompt_service.build_prompt_context",
                new=AsyncMock(return_value="<persona_system>core</persona_system>"),
            ) as build_prompt_context,
            patch(
                "app.services.persona_service.get_persona_context_for_agent",
                new=AsyncMock(return_value="<personality>Persona</personality>"),
            ),
        ):
            result = await inject_agent_mandates(
                persona_agent,
                mock_db,
                task_type="heartbeat",
            )

        assert result.system_content == (
            "<persona_system>core</persona_system>\n\n"
            "<persona_context>\n<personality>Persona</personality>\n</persona_context>"
        )
        build_prompt_context.assert_awaited_once_with(
            mock_db,
            persona_agent.id,
            include_roles=None,
            exclude_roles=[
                "autocode",
                "persona-personality",
                "persona-user-context",
                "heartbeat-instructions",
            ],
            agent_slug="persona",
        )

    @pytest.mark.asyncio
    async def test_inject_agent_mandates_excludes_autocode_role_for_non_autocode_runtime(self):
        from datetime import UTC, datetime

        agent = AgentDTO(
            id=7,
            slug="refactor",
            name="Refactor",
            description=None,
            system_prompt="Refactor safely.",
            primary_model_id=CLAUDE_SONNET,
            fallback_models=[],
            escalation_model_id=None,
            strategies={},
            temperature=0.3,
            thinking_level="medium",
            verbosity_level=None,
            is_active=True,
            is_coding_agent=True,
            tool_permissions=None,
            memory_config=None,
            max_concurrency=None,
            max_subagent_concurrency=None,
            daily_token_budget=None,
            hourly_request_limit=None,
            timeout_seconds=None,
            version=1,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        assert get_runtime_excluded_prompt_roles(
            agent_slug="refactor",
            prompt_mode="full",
            task_type="wake",
        ) == ["autocode"]

        mock_db = AsyncMock()
        with (
            patch(
                "app.services.prompt_service.build_prompt_context",
                new=AsyncMock(return_value="<agent_persona>core</agent_persona>"),
            ) as build_prompt_context,
            patch(
                "app.services.persona_service.get_persona_context_for_agent",
                new=AsyncMock(return_value=None),
            ),
        ):
            result = await inject_agent_mandates(
                agent,
                mock_db,
                task_type="wake",
            )

        assert result.system_content == "<agent_persona>core</agent_persona>"
        build_prompt_context.assert_awaited_once_with(
            mock_db,
            agent.id,
            include_roles=None,
            exclude_roles=["autocode"],
            agent_slug="refactor",
        )


class TestCompleteWithFallback:

    @pytest.mark.asyncio
    async def test_primary_succeeds(self, mock_agent: AgentDTO) -> None:
        mock_result = MagicMock()
        mock_result.content = "Hello!"

        with (
            patch("app.services.agent_routing_completion.get_adapter") as mock_get_adapter,
            patch("app.services.agent_routing_completion.record_provider_success") as record_success,
        ):
            mock_adapter = AsyncMock()
            mock_adapter.complete = AsyncMock(return_value=mock_result)
            mock_get_adapter.return_value = mock_adapter

            result = await complete_with_fallback(
                messages=[Message(role="user", content="Hi")],
                agent=mock_agent,
                max_tokens=100,
                temperature=0.7,
            )

        assert isinstance(result, CompletionResult)
        assert result.result == mock_result
        assert result.model_used == CLAUDE_SONNET
        assert result.used_fallback is False
        record_success.assert_called_once()

    @pytest.mark.asyncio
    async def test_codex_primary_maps_thinking_to_reasoning_and_verbosity(self) -> None:
        from datetime import UTC, datetime

        agent = AgentDTO(
            id=6,
            slug="codex-coder",
            name="Codex Coder",
            description=None,
            system_prompt="Write code.",
            primary_model_id="codex/gpt-5.4",
            fallback_models=[],
            escalation_model_id=None,
            strategies={},
            temperature=0.7,
            thinking_level="xhigh",
            verbosity_level="high",
            is_active=True,
            is_coding_agent=True,
            tool_permissions=None,
            memory_config=None,
            max_concurrency=None,
            max_subagent_concurrency=None,
            daily_token_budget=None,
            hourly_request_limit=None,
            timeout_seconds=None,
            version=1,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        mock_result = MagicMock()
        captured = _CapturedCall()

        async def mock_complete(**kwargs: object) -> MagicMock:
            captured.kwargs = kwargs
            return mock_result

        with patch("app.services.agent_routing_completion.get_adapter") as mock_get_adapter:
            mock_adapter = AsyncMock()
            mock_adapter.complete = mock_complete
            mock_get_adapter.return_value = mock_adapter

            result = await complete_with_fallback(
                messages=[Message(role="user", content="Hi")],
                agent=agent,
                max_tokens=100,
                temperature=0.7,
                thinking_level=agent.thinking_level,
            )

        assert result.model_used == "codex/gpt-5.4"
        assert captured.kwargs is not None
        assert captured.kwargs["reasoning_effort"] == "xhigh"
        assert "thinking_level" not in captured.kwargs
        assert captured.kwargs["verbosity_level"] == "high"

    @pytest.mark.asyncio
    async def test_primary_fails_fallback_succeeds(self, mock_agent: AgentDTO) -> None:
        mock_result = MagicMock()
        mock_result.content = "Hello from fallback!"

        call_count = 0

        async def mock_complete(**kwargs: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RateLimitError(provider="claude", retry_after=60)
            return mock_result

        with (
            patch("app.services.agent_routing_completion.get_adapter") as mock_get_adapter,
            patch("app.services.agent_routing_completion.record_provider_failure") as record_failure,
        ):
            mock_adapter = AsyncMock()
            mock_adapter.complete = mock_complete
            mock_get_adapter.return_value = mock_adapter

            result = await complete_with_fallback(
                messages=[Message(role="user", content="Hi")],
                agent=mock_agent,
                max_tokens=100,
                temperature=0.7,
            )

        assert isinstance(result, CompletionResult)
        assert result.result == mock_result
        assert result.model_used == CLAUDE_HAIKU
        assert result.used_fallback is True
        assert result.fallback_reason == "RateLimitError: Rate limit exceeded for claude"
        assert record_failure.call_count >= 1

    @pytest.mark.asyncio
    async def test_all_models_fail(self, mock_agent: AgentDTO) -> None:
        async def mock_complete(**kwargs: object) -> None:
            raise ProviderError(provider="test", message="API error")

        with patch("app.services.agent_routing_completion.get_adapter") as mock_get_adapter:
            mock_adapter = AsyncMock()
            mock_adapter.complete = mock_complete
            mock_get_adapter.return_value = mock_adapter

            with pytest.raises(ProviderError) as exc_info:
                await complete_with_fallback(
                    messages=[Message(role="user", content="Hi")],
                    agent=mock_agent,
                    max_tokens=100,
                    temperature=0.7,
                )

        assert "All models failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_no_fallbacks_primary_succeeds(self, mock_agent_no_fallbacks: AgentDTO) -> None:
        mock_result = MagicMock()
        mock_result.content = "Success!"

        with patch("app.services.agent_routing_completion.get_adapter") as mock_get_adapter:
            mock_adapter = AsyncMock()
            mock_adapter.complete = AsyncMock(return_value=mock_result)
            mock_get_adapter.return_value = mock_adapter

            result = await complete_with_fallback(
                messages=[Message(role="user", content="Hi")],
                agent=mock_agent_no_fallbacks,
                max_tokens=100,
                temperature=0.5,
            )

        assert result.model_used == CLAUDE_HAIKU
        assert result.used_fallback is False


    @pytest.mark.asyncio
    async def test_escalation_succeeds_after_fallbacks_fail(self) -> None:
        """When primary + fallbacks fail, escalation_model_id is tried."""
        from datetime import UTC, datetime

        agent = AgentDTO(
            id=3, slug="escalator", name="Escalator",
            description=None, system_prompt="Prompt.",
            primary_model_id=CLAUDE_HAIKU,
            fallback_models=[GEMINI_FLASH],
            escalation_model_id=CLAUDE_OPUS,
            strategies={}, temperature=0.7, thinking_level=None, verbosity_level=None,
            is_active=True, is_coding_agent=False,
            tool_permissions=None, memory_config=None,
            max_concurrency=None, max_subagent_concurrency=None,
            daily_token_budget=None, hourly_request_limit=None,
            timeout_seconds=None,
            version=1,
            created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
        )
        mock_result = MagicMock()
        mock_result.content = "Escalation worked!"
        call_count = 0

        async def mock_complete(**kwargs: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            # Primary (1) and fallback (2) fail, escalation (3) succeeds
            if call_count <= 2:
                raise ProviderError(provider="test", message="fail")
            return mock_result

        with patch("app.services.agent_routing_completion.get_adapter") as mock_get_adapter:
            mock_adapter = AsyncMock()
            mock_adapter.complete = mock_complete
            mock_get_adapter.return_value = mock_adapter

            result = await complete_with_fallback(
                messages=[Message(role="user", content="Hi")],
                agent=agent, max_tokens=100, temperature=0.7,
            )

        assert result.model_used == CLAUDE_OPUS
        assert result.used_fallback is True
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_escalation_skipped_when_already_in_fallbacks(self) -> None:
        """Escalation model is not retried if it was already in the fallback chain."""
        from datetime import UTC, datetime

        agent = AgentDTO(
            id=4, slug="dedup", name="Dedup",
            description=None, system_prompt="Prompt.",
            primary_model_id=CLAUDE_HAIKU,
            fallback_models=[CLAUDE_OPUS],
            escalation_model_id=CLAUDE_OPUS,  # same as fallback
            strategies={}, temperature=0.7, thinking_level=None, verbosity_level=None,
            is_active=True, is_coding_agent=False,
            tool_permissions=None, memory_config=None,
            max_concurrency=None, max_subagent_concurrency=None,
            daily_token_budget=None, hourly_request_limit=None,
            timeout_seconds=None,
            version=1,
            created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
        )

        async def mock_complete(**kwargs: object) -> None:
            raise ProviderError(provider="test", message="fail")

        with patch("app.services.agent_routing_completion.get_adapter") as mock_get_adapter:
            mock_adapter = AsyncMock()
            mock_adapter.complete = mock_complete
            mock_get_adapter.return_value = mock_adapter

            with pytest.raises(ProviderError) as exc_info:
                await complete_with_fallback(
                    messages=[Message(role="user", content="Hi")],
                    agent=agent, max_tokens=100, temperature=0.7,
                )

        assert "All models failed" in str(exc_info.value)
        # Escalation model same as fallback — should NOT appear in warnings
        # (only primary + fallback warnings, no escalation attempt)
        assert f"escalation={CLAUDE_OPUS}" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_all_models_including_escalation_fail(self) -> None:
        """When primary + fallbacks + escalation all fail, ProviderError raised."""
        from datetime import UTC, datetime

        agent = AgentDTO(
            id=5, slug="all-fail", name="AllFail",
            description=None, system_prompt="Prompt.",
            primary_model_id=CLAUDE_HAIKU,
            fallback_models=[GEMINI_FLASH],
            escalation_model_id=CLAUDE_OPUS,
            strategies={}, temperature=0.7, thinking_level=None, verbosity_level=None,
            is_active=True, is_coding_agent=False,
            tool_permissions=None, memory_config=None,
            max_concurrency=None, max_subagent_concurrency=None,
            daily_token_budget=None, hourly_request_limit=None,
            timeout_seconds=None,
            version=1,
            created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
        )

        async def mock_complete(**kwargs: object) -> None:
            raise ProviderError(provider="test", message="fail")

        with patch("app.services.agent_routing_completion.get_adapter") as mock_get_adapter:
            mock_adapter = AsyncMock()
            mock_adapter.complete = mock_complete
            mock_get_adapter.return_value = mock_adapter

            with pytest.raises(ProviderError) as exc_info:
                await complete_with_fallback(
                    messages=[Message(role="user", content="Hi")],
                    agent=agent, max_tokens=100, temperature=0.7,
                )

        assert "All models failed" in str(exc_info.value)
        assert f"escalation={CLAUDE_OPUS}" in str(exc_info.value)


class TestInjectSystemPromptIntoMessages:

    def test_no_existing_system_message(self) -> None:
        messages = [
            Message(role="user", content="Hello"),
        ]

        result = inject_system_prompt_into_messages(messages, "You are helpful.")

        assert len(result) == 2
        assert result[0].role == "system"
        assert result[0].content == "You are helpful."
        assert result[1].role == "user"

    def test_existing_system_message(self) -> None:
        messages = [
            Message(role="system", content="Existing prompt."),
            Message(role="user", content="Hello"),
        ]

        result = inject_system_prompt_into_messages(messages, "Agent prompt")

        assert len(result) == 2
        assert result[0].role == "system"
        assert "Agent prompt" in result[0].content
        assert "Existing prompt." in result[0].content

    def test_does_not_modify_original(self) -> None:
        messages = [
            Message(role="user", content="Hello"),
        ]
        original_len = len(messages)

        result = inject_system_prompt_into_messages(messages, "System")

        assert len(messages) == original_len
        assert len(result) == original_len + 1
