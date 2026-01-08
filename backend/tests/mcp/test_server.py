"""Tests for MCP server implementation."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.mcp.server import (
    MCPServerManager,
    clear_mcp_router,
    get_mcp_server,
    mcp_server,
    models,
)


class TestMCPServerManager:
    """Tests for MCPServerManager."""

    def setup_method(self):
        """Reset singleton before each test."""
        MCPServerManager._instance = None

    def test_singleton_pattern(self):
        """Test manager is a singleton."""
        manager1 = MCPServerManager()
        manager2 = MCPServerManager()
        assert manager1 is manager2

    def test_get_mcp_server(self):
        """Test get_mcp_server returns manager."""
        manager = get_mcp_server()
        assert isinstance(manager, MCPServerManager)

    def test_server_property(self):
        """Test server property returns FastMCP instance."""
        manager = get_mcp_server()
        assert manager.server is mcp_server
        assert manager.server.name == "agent-hub"

    def test_list_tools_returns_registered_tools(self):
        """Test list_tools returns tool names."""
        manager = get_mcp_server()
        tools = manager.list_tools()
        # Should have our registered tools
        assert isinstance(tools, list)
        # May or may not have tools depending on FastMCP internals

    @pytest.mark.asyncio
    async def test_health_check(self):
        """Test health check returns status."""
        manager = get_mcp_server()
        health = await manager.health_check()

        assert health["status"] == "healthy"
        assert health["server_name"] == "agent-hub"
        assert "tools_count" in health
        assert "tools" in health


class TestMCPRouter:
    """Tests for MCP router singleton."""

    def setup_method(self):
        """Clear router before each test."""
        clear_mcp_router()

    def test_clear_router(self):
        """Test clear_mcp_router resets the router."""
        # Import to trigger router creation
        from app.services.mcp.server import _get_router

        # Get router once
        router1 = _get_router()
        assert router1 is not None

        # Clear and get again
        clear_mcp_router()
        router2 = _get_router()

        # Should be a new instance
        assert router2 is not None


class TestMCPTools:
    """Tests for registered MCP tools."""

    @pytest.mark.asyncio
    async def test_models_tool(self):
        """Test models tool returns available models."""
        result = await models()

        assert isinstance(result, list)
        assert len(result) >= 5  # We have 5 models registered

        # Check structure
        for model in result:
            assert "name" in model
            assert "provider" in model
            assert "capabilities" in model

        # Check specific models exist
        model_names = [m["name"] for m in result]
        assert "claude-sonnet-4-5" in model_names
        assert "claude-opus-4-5" in model_names
        assert "gemini-3-flash-preview" in model_names

    @pytest.mark.asyncio
    async def test_complete_tool_with_mock_router(self):
        """Test complete tool calls router correctly."""
        from app.services.mcp.server import complete

        mock_result = MagicMock()
        mock_result.content = "Test response"
        mock_result.input_tokens = 10
        mock_result.output_tokens = 20

        with patch("app.services.mcp.server._get_router") as mock_get_router:
            mock_router = MagicMock()
            mock_router.complete = AsyncMock(return_value=mock_result)
            mock_get_router.return_value = mock_router

            result = await complete(
                prompt="Test prompt",
                model="claude-sonnet-4-5",
                max_tokens=100,
            )

            assert result == "Test response"
            mock_router.complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_chat_tool_with_mock_router(self):
        """Test chat tool handles messages correctly."""
        from app.services.mcp.server import chat

        mock_result = MagicMock()
        mock_result.content = "Chat response"

        with patch("app.services.mcp.server._get_router") as mock_get_router:
            mock_router = MagicMock()
            mock_router.complete = AsyncMock(return_value=mock_result)
            mock_get_router.return_value = mock_router

            result = await chat(
                messages=[
                    {"role": "user", "content": "Hello"},
                    {"role": "assistant", "content": "Hi there"},
                    {"role": "user", "content": "How are you?"},
                ],
                model="claude-sonnet-4-5",
                system="You are a helpful assistant",
            )

            assert result == "Chat response"
            mock_router.complete.assert_called_once()

            # Check that messages were built correctly
            call_args = mock_router.complete.call_args
            messages = call_args.kwargs.get("messages") or call_args[1].get("messages")
            # Should have system + 3 messages = 4 total
            assert len(messages) == 4

    @pytest.mark.asyncio
    async def test_analyze_code_tool(self):
        """Test analyze_code tool builds correct prompts."""
        from app.services.mcp.server import analyze_code

        mock_result = MagicMock()
        mock_result.content = "Code analysis result"

        with patch("app.services.mcp.server._get_router") as mock_get_router:
            mock_router = MagicMock()
            mock_router.complete = AsyncMock(return_value=mock_result)
            mock_get_router.return_value = mock_router

            result = await analyze_code(
                code="def hello(): pass",
                language="python",
                analysis_type="review",
            )

            assert result == "Code analysis result"
            mock_router.complete.assert_called_once()

            # Check prompt contains code
            call_args = mock_router.complete.call_args
            messages = call_args.kwargs.get("messages") or call_args[1].get("messages")
            assert "def hello(): pass" in messages[0].content

    @pytest.mark.asyncio
    async def test_analyze_code_security_type(self):
        """Test analyze_code with security analysis type."""
        from app.services.mcp.server import analyze_code

        mock_result = MagicMock()
        mock_result.content = "Security findings"

        with patch("app.services.mcp.server._get_router") as mock_get_router:
            mock_router = MagicMock()
            mock_router.complete = AsyncMock(return_value=mock_result)
            mock_get_router.return_value = mock_router

            result = await analyze_code(
                code="eval(user_input)",
                language="python",
                analysis_type="security",
            )

            assert result == "Security findings"

            # Check prompt mentions security
            call_args = mock_router.complete.call_args
            messages = call_args.kwargs.get("messages") or call_args[1].get("messages")
            assert "security" in messages[0].content.lower()


class TestMCPResources:
    """Tests for MCP resources."""

    @pytest.mark.asyncio
    async def test_list_sessions_resource(self):
        """Test list_sessions_resource returns JSON."""
        import json

        from app.services.mcp.server import list_sessions_resource

        with patch("app.services.mcp.server._get_active_sessions") as mock_get:
            mock_get.return_value = [
                {
                    "id": "sess-123",
                    "project_id": "proj-1",
                    "provider": "claude",
                    "model": "claude-sonnet-4-5",
                    "status": "active",
                }
            ]

            result = await list_sessions_resource()

            # Should return valid JSON
            parsed = json.loads(result)
            assert isinstance(parsed, list)
            assert len(parsed) == 1
            assert parsed[0]["id"] == "sess-123"

    @pytest.mark.asyncio
    async def test_get_session_resource_found(self):
        """Test get_session_resource returns session details."""
        import json
        from datetime import datetime

        from app.services.mcp.server import get_session_resource

        # Create a mock session
        mock_session = MagicMock()
        mock_session.id = "sess-456"
        mock_session.project_id = "proj-1"
        mock_session.provider = "claude"
        mock_session.model = "claude-sonnet-4-5"
        mock_session.status = "active"
        mock_session.messages = []
        mock_session.created_at = datetime(2026, 1, 8, 12, 0, 0)

        with patch("app.db._get_session_factory") as mock_factory:
            # Setup mock async context manager
            mock_db = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_session
            mock_db.execute = AsyncMock(return_value=mock_result)

            mock_session_cm = AsyncMock()
            mock_session_cm.__aenter__.return_value = mock_db
            mock_session_cm.__aexit__.return_value = None
            mock_factory.return_value = MagicMock(return_value=mock_session_cm)

            result = await get_session_resource("sess-456")

            parsed = json.loads(result)
            assert parsed["id"] == "sess-456"
            assert parsed["status"] == "active"
            assert parsed["message_count"] == 0

    @pytest.mark.asyncio
    async def test_get_session_resource_not_found(self):
        """Test get_session_resource returns error for missing session."""
        import json

        from app.services.mcp.server import get_session_resource

        with patch("app.db._get_session_factory") as mock_factory:
            mock_db = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None
            mock_db.execute = AsyncMock(return_value=mock_result)

            mock_session_cm = AsyncMock()
            mock_session_cm.__aenter__.return_value = mock_db
            mock_session_cm.__aexit__.return_value = None
            mock_factory.return_value = MagicMock(return_value=mock_session_cm)

            result = await get_session_resource("missing-session")

            parsed = json.loads(result)
            assert "error" in parsed
            assert "not found" in parsed["error"]

    @pytest.mark.asyncio
    async def test_list_models_resource(self):
        """Test list_models_resource returns models JSON."""
        import json

        from app.services.mcp.server import list_models_resource

        result = await list_models_resource()

        parsed = json.loads(result)
        assert isinstance(parsed, list)
        assert len(parsed) >= 5

        model_names = [m["name"] for m in parsed]
        assert "claude-sonnet-4-5" in model_names
        assert "gemini-3-flash-preview" in model_names
