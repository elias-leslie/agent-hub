"""Tests for agent routing service."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.adapters.base import Message, ProviderError, RateLimitError
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


@pytest.fixture
def mock_agent():
    """Create a mock AgentDTO."""
    from datetime import UTC, datetime

    return AgentDTO(
        id=1,
        slug="coder",
        name="Coder Agent",
        description="A coding assistant",
        system_prompt="You are a helpful coding assistant.",
        primary_model_id="claude-sonnet-4-5",
        fallback_models=["claude-haiku-4-5", "gemini-3-flash"],
        escalation_model_id=None,
        strategies={},
        mandate_tags=["coding", "implementation"],
        temperature=0.7,
        max_tokens=4096,
        is_active=True,
        version=1,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.fixture
def mock_agent_no_fallbacks():
    """Create a mock AgentDTO without fallbacks."""
    from datetime import UTC, datetime

    return AgentDTO(
        id=2,
        slug="simple",
        name="Simple Agent",
        description=None,
        system_prompt="Simple prompt.",
        primary_model_id="claude-haiku-4-5",
        fallback_models=[],
        escalation_model_id=None,
        strategies={},
        mandate_tags=[],
        temperature=0.5,
        max_tokens=2048,
        is_active=True,
        version=1,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


class TestGetProviderForModel:
    """Tests for get_provider_for_model."""

    def test_claude_model(self):
        assert get_provider_for_model("claude-sonnet-4-5") == "claude"
        assert get_provider_for_model("claude-haiku-4-5") == "claude"
        assert get_provider_for_model("claude-opus-4-5") == "claude"

    def test_gemini_model(self):
        assert get_provider_for_model("gemini-3-flash") == "gemini"
        assert get_provider_for_model("gemini-3-pro") == "gemini"

    def test_unknown_defaults_to_claude(self):
        assert get_provider_for_model("unknown-model") == "claude"


class TestGetAdapter:
    """Tests for get_adapter."""

    def test_claude_adapter(self):
        from app.adapters.claude import ClaudeAdapter

        adapter = get_adapter("claude")
        assert isinstance(adapter, ClaudeAdapter)

    def test_gemini_adapter(self):
        from app.adapters.gemini import GeminiAdapter

        adapter = get_adapter("gemini")
        assert isinstance(adapter, GeminiAdapter)

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown provider"):
            get_adapter("unknown")


class TestResolveAgent:
    """Tests for resolve_agent."""

    @pytest.mark.asyncio
    async def test_found_agent(self, mock_agent):
        mock_db = AsyncMock()
        mock_service = MagicMock()
        mock_service.get_by_slug = AsyncMock(return_value=mock_agent)

        with patch("app.services.agent_routing.get_agent_service", return_value=mock_service):
            result = await resolve_agent("coder", mock_db)

        assert isinstance(result, ResolvedAgent)
        assert result.agent == mock_agent
        assert result.model == "claude-sonnet-4-5"
        assert result.provider == "claude"
        mock_service.get_by_slug.assert_called_once_with(mock_db, "coder")

    @pytest.mark.asyncio
    async def test_agent_not_found(self):
        mock_db = AsyncMock()
        mock_service = MagicMock()
        mock_service.get_by_slug = AsyncMock(return_value=None)

        with (
            patch("app.services.agent_routing.get_agent_service", return_value=mock_service),
            pytest.raises(HTTPException) as exc_info,
        ):
            await resolve_agent("unknown", mock_db)

        assert exc_info.value.status_code == 404
        assert "Agent 'unknown' not found" in str(exc_info.value.detail)


class TestInjectAgentMandates:
    """Tests for inject_agent_mandates."""

    @pytest.mark.asyncio
    async def test_with_mandate_tags(self, mock_agent):
        with patch(
            "app.services.memory.build_agent_mandate_context",
            new_callable=AsyncMock,
        ) as mock_build:
            mock_build.return_value = ("## Mandates\n- Rule 1", ["uuid1", "uuid2"])

            result = await inject_agent_mandates(mock_agent)

        assert isinstance(result, MandateInjection)
        assert "You are a helpful coding assistant." in result.system_content
        assert "## Mandates" in result.system_content
        assert result.injected_uuids == ["uuid1", "uuid2"]

    @pytest.mark.asyncio
    async def test_without_mandate_tags(self, mock_agent_no_fallbacks):
        result = await inject_agent_mandates(mock_agent_no_fallbacks)

        assert isinstance(result, MandateInjection)
        assert result.system_content == "Simple prompt."
        assert result.injected_uuids == []

    @pytest.mark.asyncio
    async def test_mandate_injection_error_logged(self, mock_agent, caplog):
        with patch(
            "app.services.memory.build_agent_mandate_context",
            new_callable=AsyncMock,
        ) as mock_build:
            mock_build.side_effect = Exception("Connection failed")

            result = await inject_agent_mandates(mock_agent)

        # Should gracefully handle error
        assert result.system_content == "You are a helpful coding assistant."
        assert result.injected_uuids == []
        assert "Failed to inject mandates" in caplog.text


class TestCompleteWithFallback:
    """Tests for complete_with_fallback."""

    @pytest.mark.asyncio
    async def test_primary_succeeds(self, mock_agent):
        mock_result = MagicMock()
        mock_result.content = "Hello!"

        with patch("app.services.agent_routing.get_adapter") as mock_get_adapter:
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
        assert result.model_used == "claude-sonnet-4-5"
        assert result.used_fallback is False

    @pytest.mark.asyncio
    async def test_primary_fails_fallback_succeeds(self, mock_agent):
        mock_result = MagicMock()
        mock_result.content = "Hello from fallback!"

        call_count = 0

        async def mock_complete(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Primary fails
                raise RateLimitError(provider="claude", retry_after=60)
            return mock_result

        with patch("app.services.agent_routing.get_adapter") as mock_get_adapter:
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
        assert result.model_used == "claude-haiku-4-5"  # First fallback
        assert result.used_fallback is True

    @pytest.mark.asyncio
    async def test_all_models_fail(self, mock_agent):
        async def mock_complete(**kwargs):
            raise ProviderError(provider="test", message="API error")

        with patch("app.services.agent_routing.get_adapter") as mock_get_adapter:
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
    async def test_no_fallbacks_primary_succeeds(self, mock_agent_no_fallbacks):
        mock_result = MagicMock()
        mock_result.content = "Success!"

        with patch("app.services.agent_routing.get_adapter") as mock_get_adapter:
            mock_adapter = AsyncMock()
            mock_adapter.complete = AsyncMock(return_value=mock_result)
            mock_get_adapter.return_value = mock_adapter

            result = await complete_with_fallback(
                messages=[Message(role="user", content="Hi")],
                agent=mock_agent_no_fallbacks,
                max_tokens=100,
                temperature=0.5,
            )

        assert result.model_used == "claude-haiku-4-5"
        assert result.used_fallback is False


class TestInjectSystemPromptIntoMessages:
    """Tests for inject_system_prompt_into_messages."""

    def test_no_existing_system_message(self):
        messages = [
            Message(role="user", content="Hello"),
        ]

        result = inject_system_prompt_into_messages(messages, "You are helpful.")

        assert len(result) == 2
        assert result[0].role == "system"
        assert result[0].content == "You are helpful."
        assert result[1].role == "user"

    def test_existing_system_message(self):
        messages = [
            Message(role="system", content="Existing prompt."),
            Message(role="user", content="Hello"),
        ]

        result = inject_system_prompt_into_messages(messages, "Agent prompt")

        assert len(result) == 2
        assert result[0].role == "system"
        assert "Agent prompt" in result[0].content
        assert "Existing prompt." in result[0].content

    def test_does_not_modify_original(self):
        messages = [
            Message(role="user", content="Hello"),
        ]
        original_len = len(messages)

        result = inject_system_prompt_into_messages(messages, "System")

        # Original unchanged
        assert len(messages) == original_len
        # Result has new message
        assert len(result) == original_len + 1
