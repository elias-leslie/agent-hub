"""Tests for programmatic tool calling support."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from app.services.container_manager import (
    Container,
    ContainerManager,
    clear_container_manager,
    get_container_manager,
)
from app.services.tools.base import (
    CodeExecutionTool,
    Tool,
    ToolCall,
    ToolCaller,
    ToolRegistry,
)
from app.services.tools.claude_tools import (
    ContainerInfo,
    ServerToolUse,
    format_continuation_message,
    format_tools_for_api,
    parse_tool_calls,
)


class TestCallerTypes:
    """Tests for ToolCaller and caller type handling."""

    def test_default_caller_is_direct(self):
        """Test that default tool caller is direct."""
        call = ToolCall(id="t1", name="test", input={})
        assert call.caller.type == "direct"
        assert call.caller.tool_id is None

    def test_programmatic_caller(self):
        """Test programmatic tool caller with tool_id."""
        caller = ToolCaller(
            type="code_execution_20250825", tool_id="srvtoolu_abc123"
        )
        call = ToolCall(id="t1", name="test", input={}, caller=caller)

        assert call.caller.type == "code_execution_20250825"
        assert call.caller.tool_id == "srvtoolu_abc123"


class TestToolAllowedCallers:
    """Tests for allowed_callers field on tools."""

    def test_default_allowed_callers_is_direct(self):
        """Test that default allowed_callers is ['direct']."""
        tool = Tool(
            name="test_tool",
            description="A test tool",
            input_schema={"type": "object"},
        )
        assert tool.allowed_callers == ["direct"]

    def test_programmatic_only_tool(self):
        """Test tool only callable from code execution."""
        tool = Tool(
            name="query_db",
            description="Query database",
            input_schema={"type": "object"},
            allowed_callers=["code_execution_20250825"],
        )
        assert "direct" not in tool.allowed_callers
        assert "code_execution_20250825" in tool.allowed_callers

    def test_both_callers_allowed(self):
        """Test tool callable from both direct and code execution."""
        tool = Tool(
            name="get_weather",
            description="Get weather",
            input_schema={"type": "object"},
            allowed_callers=["direct", "code_execution_20250825"],
        )
        assert "direct" in tool.allowed_callers
        assert "code_execution_20250825" in tool.allowed_callers


class TestToolRegistryAllowedCallers:
    """Tests for ToolRegistry with allowed_callers."""

    def test_api_format_omits_default_allowed_callers(self):
        """Test that default allowed_callers is not included in API format."""
        registry = ToolRegistry(
            tools=[
                Tool(
                    name="direct_tool",
                    description="Direct only",
                    input_schema={"type": "object"},
                    # Default: allowed_callers=["direct"]
                )
            ]
        )

        result = registry.to_api_format("claude")

        assert len(result) == 1
        assert "allowed_callers" not in result[0]

    def test_api_format_includes_non_default_allowed_callers(self):
        """Test that non-default allowed_callers is included in API format."""
        registry = ToolRegistry(
            tools=[
                Tool(
                    name="programmatic_tool",
                    description="Programmatic only",
                    input_schema={"type": "object"},
                    allowed_callers=["code_execution_20250825"],
                )
            ]
        )

        result = registry.to_api_format("claude")

        assert len(result) == 1
        assert result[0]["allowed_callers"] == ["code_execution_20250825"]

    def test_api_format_with_code_execution(self):
        """Test including code_execution tool in API format."""
        registry = ToolRegistry(
            tools=[
                Tool(
                    name="query_db",
                    description="Query database",
                    input_schema={"type": "object"},
                    allowed_callers=["code_execution_20250825"],
                )
            ]
        )

        result = registry.to_api_format("claude", include_code_execution=True)

        assert len(result) == 2
        # First tool should be code_execution
        assert result[0]["type"] == "code_execution_20250825"
        assert result[0]["name"] == "code_execution"
        # Second tool is our custom tool
        assert result[1]["name"] == "query_db"

    def test_is_caller_allowed_direct(self):
        """Test is_caller_allowed for direct caller."""
        registry = ToolRegistry(
            tools=[
                Tool(
                    name="direct_only",
                    description="Test",
                    input_schema={"type": "object"},
                    allowed_callers=["direct"],
                )
            ]
        )

        assert registry.is_caller_allowed("direct_only", "direct") is True
        assert registry.is_caller_allowed("direct_only", "code_execution_20250825") is False

    def test_is_caller_allowed_programmatic(self):
        """Test is_caller_allowed for programmatic caller."""
        registry = ToolRegistry(
            tools=[
                Tool(
                    name="programmatic_only",
                    description="Test",
                    input_schema={"type": "object"},
                    allowed_callers=["code_execution_20250825"],
                )
            ]
        )

        assert registry.is_caller_allowed("programmatic_only", "direct") is False
        assert registry.is_caller_allowed("programmatic_only", "code_execution_20250825") is True

    def test_is_caller_allowed_nonexistent_tool(self):
        """Test is_caller_allowed returns False for nonexistent tool."""
        registry = ToolRegistry()
        assert registry.is_caller_allowed("nonexistent", "direct") is False


class TestCodeExecutionTool:
    """Tests for CodeExecutionTool."""

    def test_default_type_and_name(self):
        """Test default code execution tool type and name."""
        tool = CodeExecutionTool()
        assert tool.type == "code_execution_20250825"
        assert tool.name == "code_execution"

    def test_to_api_format(self):
        """Test API format for code execution tool."""
        tool = CodeExecutionTool()
        result = tool.to_api_format()

        assert result["type"] == "code_execution_20250825"
        assert result["name"] == "code_execution"
        assert "input_schema" not in result
        assert "description" not in result


class TestParseToolCallsWithCaller:
    """Tests for parsing tool calls with caller information."""

    def test_parse_direct_tool_call(self):
        """Test parsing direct tool call (no caller field)."""
        from anthropic.types import ToolUseBlock as RealToolUseBlock

        tool_block = MagicMock(spec=["id", "name", "input", "type"])
        tool_block.id = "toolu_123"
        tool_block.name = "get_weather"
        tool_block.input = {"location": "NYC"}
        tool_block.__class__ = RealToolUseBlock
        tool_block.type = "tool_use"
        # No caller attribute - spec limits to listed attrs

        result = parse_tool_calls([tool_block])

        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].caller.type == "direct"
        assert result.tool_calls[0].caller.tool_id is None

    def test_parse_programmatic_tool_call(self):
        """Test parsing programmatic tool call with caller field."""
        from anthropic.types import ToolUseBlock as RealToolUseBlock

        tool_block = MagicMock()
        tool_block.id = "toolu_456"
        tool_block.name = "query_db"
        tool_block.input = {"sql": "SELECT *"}
        tool_block.__class__ = RealToolUseBlock
        tool_block.type = "tool_use"
        # Simulate caller field
        tool_block.caller = MagicMock()
        tool_block.caller.type = "code_execution_20250825"
        tool_block.caller.tool_id = "srvtoolu_abc123"

        result = parse_tool_calls([tool_block])

        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].caller.type == "code_execution_20250825"
        assert result.tool_calls[0].caller.tool_id == "srvtoolu_abc123"

    def test_parse_container_info(self):
        """Test parsing container info from response."""
        from anthropic.types import TextBlock as RealTextBlock

        text_block = MagicMock()
        text_block.text = "Hello"
        text_block.__class__ = RealTextBlock
        text_block.type = "text"

        container_data = {
            "id": "container_xyz789",
            "expires_at": "2026-01-15T14:30:00Z",
        }

        result = parse_tool_calls([text_block], container_data=container_data)

        assert result.container is not None
        assert result.container.id == "container_xyz789"
        assert result.container.expires_at == "2026-01-15T14:30:00Z"

    def test_parse_server_tool_use(self):
        """Test parsing server_tool_use block (code_execution)."""
        # Create a mock for server_tool_use block
        server_block = MagicMock()
        server_block.type = "server_tool_use"
        server_block.id = "srvtoolu_abc123"
        server_block.name = "code_execution"
        server_block.input = {"code": "print('hello')"}

        result = parse_tool_calls([server_block])

        assert len(result.server_tool_uses) == 1
        assert result.server_tool_uses[0].id == "srvtoolu_abc123"
        assert result.server_tool_uses[0].name == "code_execution"


class TestFormatContinuationMessage:
    """Tests for format_continuation_message."""

    def test_format_single_result(self):
        """Test formatting single tool result."""
        from app.services.tools.base import ToolResult

        results = [
            ToolResult(
                tool_use_id="toolu_123",
                content='{"weather": "sunny"}',
                is_error=False,
            )
        ]

        message = format_continuation_message(results)

        assert message["role"] == "user"
        assert len(message["content"]) == 1
        assert message["content"][0]["type"] == "tool_result"
        assert message["content"][0]["tool_use_id"] == "toolu_123"

    def test_format_multiple_results(self):
        """Test formatting multiple tool results."""
        from app.services.tools.base import ToolResult

        results = [
            ToolResult(tool_use_id="t1", content="result 1", is_error=False),
            ToolResult(tool_use_id="t2", content="result 2", is_error=False),
            ToolResult(tool_use_id="t3", content="error", is_error=True),
        ]

        message = format_continuation_message(results)

        assert len(message["content"]) == 3
        assert all(c["type"] == "tool_result" for c in message["content"])
        assert message["content"][2]["is_error"] is True


class TestContainerManager:
    """Tests for ContainerManager."""

    def setup_method(self):
        """Clear container manager before each test."""
        clear_container_manager()

    def test_register_container(self):
        """Test registering a new container."""
        manager = ContainerManager()
        container = manager.register(
            container_id="container_123",
            expires_at="2026-01-15T14:30:00Z",
            session_id="session_abc",
        )

        assert container.id == "container_123"
        assert container.session_id == "session_abc"
        assert not container.is_expired

    def test_get_container_by_id(self):
        """Test getting container by ID."""
        manager = ContainerManager()
        manager.register(
            container_id="container_123",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )

        container = manager.get("container_123")
        assert container is not None
        assert container.id == "container_123"

    def test_get_container_for_session(self):
        """Test getting container for session."""
        manager = ContainerManager()
        manager.register(
            container_id="container_123",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            session_id="session_abc",
        )

        container = manager.get_for_session("session_abc")
        assert container is not None
        assert container.id == "container_123"

    def test_expired_container_returns_none(self):
        """Test that expired container returns None."""
        manager = ContainerManager()
        manager.register(
            container_id="container_123",
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )

        container = manager.get("container_123")
        assert container is None

    def test_update_expiration(self):
        """Test updating container expiration."""
        manager = ContainerManager()
        manager.register(
            container_id="container_123",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=1),
        )

        new_expires = datetime.now(timezone.utc) + timedelta(minutes=10)
        updated = manager.update_expiration("container_123", new_expires)

        assert updated is not None
        assert updated.expires_at == new_expires

    def test_invalidate_container(self):
        """Test invalidating a container."""
        manager = ContainerManager()
        manager.register(
            container_id="container_123",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )

        manager.invalidate("container_123")

        assert manager.get("container_123") is None

    def test_cleanup_expired(self):
        """Test cleaning up expired containers."""
        manager = ContainerManager()
        # Add expired container
        manager.register(
            container_id="expired_1",
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
        # Add valid container
        manager.register(
            container_id="valid_1",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )

        cleaned = manager.cleanup_expired()

        assert cleaned == 1
        assert manager.get("expired_1") is None
        assert manager.get("valid_1") is not None

    def test_container_time_remaining(self):
        """Test container time_remaining property."""
        expires = datetime.now(timezone.utc) + timedelta(minutes=3)
        container = Container(id="test", expires_at=expires)

        remaining = container.time_remaining
        assert remaining.total_seconds() > 0
        assert remaining.total_seconds() <= 180

    def test_global_container_manager(self):
        """Test global container manager singleton."""
        manager1 = get_container_manager()
        manager2 = get_container_manager()

        assert manager1 is manager2


class TestFormatToolsForApiWithCodeExecution:
    """Tests for format_tools_for_api with code execution."""

    def test_without_code_execution(self):
        """Test formatting without code execution tool."""
        registry = ToolRegistry(
            tools=[
                Tool(
                    name="test",
                    description="Test tool",
                    input_schema={"type": "object"},
                )
            ]
        )

        result = format_tools_for_api(registry, include_code_execution=False)

        assert len(result) == 1
        assert result[0]["name"] == "test"

    def test_with_code_execution(self):
        """Test formatting with code execution tool."""
        registry = ToolRegistry(
            tools=[
                Tool(
                    name="query",
                    description="Query tool",
                    input_schema={"type": "object"},
                    allowed_callers=["code_execution_20250825"],
                )
            ]
        )

        result = format_tools_for_api(registry, include_code_execution=True)

        assert len(result) == 2
        assert result[0]["type"] == "code_execution_20250825"
        assert result[0]["name"] == "code_execution"
        assert result[1]["name"] == "query"
        assert result[1]["allowed_callers"] == ["code_execution_20250825"]
