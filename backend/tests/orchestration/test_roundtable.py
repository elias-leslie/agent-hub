"""Tests for roundtable multi-agent collaboration."""

from unittest.mock import MagicMock, patch

import pytest

from app.services.orchestration.roundtable import (
    RoundtableEvent,
    RoundtableMessage,
    RoundtableSession,
)


class TestRoundtableMessage:
    """Tests for RoundtableMessage dataclass."""

    def test_create_user_message(self):
        """Test creating a user message."""
        msg = RoundtableMessage.create("user", "Hello world")

        assert msg.role == "user"
        assert msg.content == "Hello world"
        assert msg.id is not None
        assert msg.tokens_used == 0

    def test_create_agent_message(self):
        """Test creating an agent message."""
        msg = RoundtableMessage.create(
            "claude",
            "Response content",
            tokens_used=150,
            model="claude-sonnet-4-5",
        )

        assert msg.role == "claude"
        assert msg.tokens_used == 150
        assert msg.model == "claude-sonnet-4-5"


class TestRoundtableSession:
    """Tests for RoundtableSession dataclass."""

    def test_create_session(self):
        """Test creating a session."""
        session = RoundtableSession.create("test-project")

        assert session.project_id == "test-project"
        assert session.mode == "quick"
        assert session.tools_enabled is True
        assert len(session.messages) == 0
        assert session.id is not None

    def test_create_session_with_options(self):
        """Test creating a session with options."""
        session = RoundtableSession.create(
            "test-project",
            mode="deliberation",
            tools_enabled=False,
        )

        assert session.mode == "deliberation"
        assert session.tools_enabled is False

    def test_add_message(self):
        """Test adding messages to session."""
        session = RoundtableSession.create("test")

        msg1 = RoundtableMessage.create("user", "Hello")
        msg2 = RoundtableMessage.create("claude", "Hi there")

        session.add_message(msg1)
        session.add_message(msg2)

        assert len(session.messages) == 2

    def test_get_context(self):
        """Test getting conversation context."""
        session = RoundtableSession.create("test")

        session.add_message(RoundtableMessage.create("user", "Hello"))
        session.add_message(RoundtableMessage.create("claude", "Hi"))
        session.add_message(RoundtableMessage.create("gemini", "Hello too"))

        context = session.get_context()

        assert "[USER]: Hello" in context
        assert "[CLAUDE]: Hi" in context
        assert "[GEMINI]: Hello too" in context

    def test_get_context_limit(self):
        """Test context limiting."""
        session = RoundtableSession.create("test")

        for i in range(30):
            session.add_message(RoundtableMessage.create("user", f"Message {i}"))

        context = session.get_context(max_messages=5)

        # Should only have last 5 messages
        assert "Message 25" in context
        assert "Message 29" in context
        assert "Message 0" not in context

    def test_total_tokens(self):
        """Test total token calculation."""
        session = RoundtableSession.create("test")

        session.add_message(RoundtableMessage.create("user", "Hello", tokens_used=10))
        session.add_message(RoundtableMessage.create("claude", "Hi there", tokens_used=50))

        assert session.total_tokens == 60


class TestRoundtableEvent:
    """Tests for RoundtableEvent dataclass."""

    def test_message_event(self):
        """Test message event."""
        event = RoundtableEvent(
            type="message",
            agent="claude",
            content="Hello",
        )

        assert event.type == "message"
        assert event.agent == "claude"
        assert event.content == "Hello"

    def test_thinking_event(self):
        """Test thinking event."""
        event = RoundtableEvent(
            type="thinking",
            agent="claude",
            content="Let me consider...",
        )

        assert event.type == "thinking"

    def test_error_event(self):
        """Test error event."""
        event = RoundtableEvent(
            type="error",
            agent="gemini",
            error="API timeout",
        )

        assert event.type == "error"
        assert event.error == "API timeout"

    def test_done_event(self):
        """Test done event."""
        event = RoundtableEvent(type="done")
        assert event.type == "done"


class TestRoundtableService:
    """Tests for RoundtableService.

    These tests mock the adapters to avoid requiring API keys.
    """

    @pytest.fixture
    def mock_adapters(self):
        """Fixture to mock Claude and Gemini adapters."""
        with (
            patch("app.services.orchestration.roundtable.ClaudeAdapter") as mock_claude,
            patch("app.services.orchestration.roundtable.GeminiAdapter") as mock_gemini,
        ):
            mock_claude_instance = MagicMock()
            mock_gemini_instance = MagicMock()
            mock_claude.return_value = mock_claude_instance
            mock_gemini.return_value = mock_gemini_instance
            yield {
                "claude": mock_claude_instance,
                "gemini": mock_gemini_instance,
            }

    def test_initialization(self, mock_adapters):
        """Test service initialization."""
        from app.constants import CLAUDE_SONNET, GEMINI_FLASH
        from app.services.orchestration.roundtable import RoundtableService

        service = RoundtableService()

        assert service._claude_model == CLAUDE_SONNET
        assert service._gemini_model == GEMINI_FLASH

    def test_custom_models(self, mock_adapters):
        """Test custom model configuration."""
        from app.services.orchestration.roundtable import RoundtableService

        service = RoundtableService(
            claude_model="claude-opus-4-5",
            gemini_model="gemini-3-pro",
        )

        assert service._claude_model == "claude-opus-4-5"
        assert service._gemini_model == "gemini-3-pro"

    def test_create_session(self, mock_adapters):
        """Test session creation."""
        from app.services.orchestration.roundtable import RoundtableService

        service = RoundtableService()
        session = service.create_session("test-project")

        assert session is not None
        assert session.project_id == "test-project"
        assert service.get_session(session.id) is session

    def test_get_nonexistent_session(self, mock_adapters):
        """Test getting non-existent session."""
        from app.services.orchestration.roundtable import RoundtableService

        service = RoundtableService()
        session = service.get_session("nonexistent")
        assert session is None

    def test_build_system_prompt(self, mock_adapters):
        """Test system prompt building."""
        from app.services.orchestration.roundtable import RoundtableService

        service = RoundtableService()

        claude_prompt = service._build_system_prompt("claude")
        gemini_prompt = service._build_system_prompt("gemini")

        assert "Claude" in claude_prompt
        assert "Gemini" in gemini_prompt
        assert "roundtable" in claude_prompt.lower()

    def test_build_prompt_with_context(self, mock_adapters):
        """Test prompt building with context."""
        from app.services.orchestration.roundtable import RoundtableService

        service = RoundtableService()

        prompt = service._build_prompt(
            "What do you think?",
            "[USER]: Previous message\n[CLAUDE]: Previous response",
            "gemini",
        )

        assert "Previous message" in prompt
        assert "Claude may have already responded" in prompt

    def test_build_prompt_without_context(self, mock_adapters):
        """Test prompt building without context."""
        from app.services.orchestration.roundtable import RoundtableService

        service = RoundtableService()

        prompt = service._build_prompt("What do you think?", "", "claude")

        assert prompt == "What do you think?"

    def test_end_session(self, mock_adapters):
        """Test ending a session."""
        from app.services.orchestration.roundtable import RoundtableService

        service = RoundtableService()
        session = service.create_session("test-project")

        session.add_message(RoundtableMessage.create("user", "Hello"))
        session.add_message(RoundtableMessage.create("claude", "Hi", tokens_used=100))

        summary = service.end_session(session)

        assert summary["session_id"] == session.id
        assert summary["message_count"] == 2
        assert summary["total_tokens"] == 100
        assert "duration_seconds" in summary

        # Session should be removed
        assert service.get_session(session.id) is None


class TestRoundtableServiceAsync:
    """Async tests for RoundtableService."""

    @pytest.fixture
    def mock_adapters(self):
        """Fixture to mock Claude and Gemini adapters."""
        with (
            patch("app.services.orchestration.roundtable.ClaudeAdapter") as mock_claude,
            patch("app.services.orchestration.roundtable.GeminiAdapter") as mock_gemini,
        ):
            mock_claude_instance = MagicMock()
            mock_gemini_instance = MagicMock()
            mock_claude.return_value = mock_claude_instance
            mock_gemini.return_value = mock_gemini_instance
            yield {
                "claude": mock_claude_instance,
                "gemini": mock_gemini_instance,
            }

    @pytest.mark.asyncio
    async def test_route_message_to_claude(self, mock_adapters):
        """Test routing message to Claude only."""
        from app.services.orchestration.roundtable import RoundtableService

        service = RoundtableService()
        session = service.create_session("test")

        mock_event = MagicMock()
        mock_event.type = "done"
        mock_event.input_tokens = 100
        mock_event.output_tokens = 50

        async def mock_stream(*args, **kwargs):
            yield MagicMock(type="content", content="Hello")
            yield mock_event

        mock_adapters["claude"].stream = mock_stream

        events = []
        async for event in service.route_message(session, "Hello", target="claude"):
            events.append(event)

        # Should have message events and done
        assert any(e.type == "message" for e in events)
        assert any(e.type == "done" for e in events)

    @pytest.mark.asyncio
    async def test_route_message_to_both(self, mock_adapters):
        """Test routing message to both agents."""
        from app.services.orchestration.roundtable import RoundtableService

        service = RoundtableService()
        session = service.create_session("test")

        mock_event = MagicMock()
        mock_event.type = "done"
        mock_event.input_tokens = 100
        mock_event.output_tokens = 50

        async def mock_stream(*args, **kwargs):
            yield MagicMock(type="content", content="Response")
            yield mock_event

        mock_adapters["claude"].stream = mock_stream
        mock_adapters["gemini"].stream = mock_stream

        events = []
        async for event in service.route_message(session, "Hello", target="both"):
            events.append(event)

        # Should have events from both agents
        claude_events = [e for e in events if e.agent == "claude"]
        gemini_events = [e for e in events if e.agent == "gemini"]

        assert len(claude_events) > 0
        assert len(gemini_events) > 0

    @pytest.mark.asyncio
    async def test_route_message_error_handling(self, mock_adapters):
        """Test error handling in message routing."""
        from app.services.orchestration.roundtable import RoundtableService

        service = RoundtableService()
        session = service.create_session("test")

        async def mock_stream_error(*args, **kwargs):
            raise Exception("API error")
            yield  # Make it a generator (unreachable but needed for syntax)

        mock_adapters["claude"].stream = mock_stream_error

        events = []
        async for event in service.route_message(session, "Hello", target="claude"):
            events.append(event)

        # Should have error event
        error_events = [e for e in events if e.type == "error"]
        assert len(error_events) == 1
        assert "API error" in error_events[0].error


class TestGetRoundtableService:
    """Tests for singleton service getter."""

    def test_singleton(self):
        """Test singleton pattern."""
        with (
            patch("app.services.orchestration.roundtable.ClaudeAdapter"),
            patch("app.services.orchestration.roundtable.GeminiAdapter"),
        ):
            import app.services.orchestration.roundtable as rt

            rt._roundtable_service = None

            from app.services.orchestration.roundtable import get_roundtable_service

            service1 = get_roundtable_service()
            service2 = get_roundtable_service()

            assert service1 is service2
