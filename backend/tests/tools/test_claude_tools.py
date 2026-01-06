"""Tests for Claude tool calling support."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.tools.base import (
    Tool,
    ToolCall,
    ToolDecision,
    ToolRegistry,
    ToolResult,
)
from app.services.tools.claude_tools import (
    ClaudeToolHandler,
    ClaudeToolResponse,
    format_tool_result,
    format_tools_for_api,
    parse_tool_calls,
)


class TestToolRegistry:
    """Tests for ToolRegistry."""

    def test_add_and_get_tool(self):
        """Test adding and retrieving tools."""
        registry = ToolRegistry()
        tool = Tool(
            name="test_tool",
            description="A test tool",
            input_schema={"type": "object", "properties": {"x": {"type": "string"}}},
        )
        registry.add(tool)

        assert registry.get("test_tool") == tool
        assert registry.get("nonexistent") is None

    def test_to_api_format_claude(self):
        """Test Claude API format conversion."""
        registry = ToolRegistry(
            tools=[
                Tool(
                    name="get_weather",
                    description="Get weather for a location",
                    input_schema={
                        "type": "object",
                        "properties": {"location": {"type": "string"}},
                        "required": ["location"],
                    },
                )
            ]
        )

        result = registry.to_api_format("claude")

        assert len(result) == 1
        assert result[0]["name"] == "get_weather"
        assert result[0]["description"] == "Get weather for a location"
        assert "input_schema" in result[0]

    def test_to_api_format_gemini(self):
        """Test Gemini API format conversion."""
        registry = ToolRegistry(
            tools=[
                Tool(
                    name="get_weather",
                    description="Get weather for a location",
                    input_schema={
                        "type": "object",
                        "properties": {"location": {"type": "string"}},
                    },
                )
            ]
        )

        result = registry.to_api_format("gemini")

        assert len(result) == 1
        assert result[0]["name"] == "get_weather"
        # Gemini uses "parameters" instead of "input_schema"
        assert "parameters" in result[0]

    def test_to_api_format_unknown_provider(self):
        """Test unknown provider raises error."""
        registry = ToolRegistry()
        with pytest.raises(ValueError, match="Unknown provider"):
            registry.to_api_format("unknown")


class TestParseToolCalls:
    """Tests for parse_tool_calls."""

    def test_parse_text_only(self):
        """Test parsing response with only text."""
        text_block = MagicMock()
        text_block.text = "Hello, world!"
        type(text_block).__name__ = "TextBlock"

        # Make isinstance work for TextBlock
        from anthropic.types import TextBlock as RealTextBlock

        text_block.__class__ = RealTextBlock
        text_block.type = "text"

        result = parse_tool_calls([text_block])

        assert result.text_content == "Hello, world!"
        assert len(result.tool_calls) == 0

    def test_parse_tool_use_only(self):
        """Test parsing response with only tool use."""
        from anthropic.types import ToolUseBlock as RealToolUseBlock

        tool_block = MagicMock()
        tool_block.id = "tool_123"
        tool_block.name = "get_weather"
        tool_block.input = {"location": "NYC"}
        tool_block.__class__ = RealToolUseBlock
        tool_block.type = "tool_use"

        result = parse_tool_calls([tool_block])

        assert result.text_content == ""
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].id == "tool_123"
        assert result.tool_calls[0].name == "get_weather"
        assert result.tool_calls[0].input == {"location": "NYC"}

    def test_parse_mixed_content(self):
        """Test parsing response with text and tool use."""
        from anthropic.types import TextBlock as RealTextBlock
        from anthropic.types import ToolUseBlock as RealToolUseBlock

        text_block = MagicMock()
        text_block.text = "Let me check the weather."
        text_block.__class__ = RealTextBlock
        text_block.type = "text"

        tool_block = MagicMock()
        tool_block.id = "tool_456"
        tool_block.name = "get_weather"
        tool_block.input = {"location": "London"}
        tool_block.__class__ = RealToolUseBlock
        tool_block.type = "tool_use"

        result = parse_tool_calls([text_block, tool_block])

        assert result.text_content == "Let me check the weather."
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "get_weather"


class TestFormatToolResult:
    """Tests for format_tool_result."""

    def test_format_success_result(self):
        """Test formatting successful tool result."""
        result = ToolResult(
            tool_use_id="tool_123",
            content="Weather: Sunny, 72°F",
            is_error=False,
        )

        formatted = format_tool_result(result)

        assert formatted["type"] == "tool_result"
        assert formatted["tool_use_id"] == "tool_123"
        assert formatted["content"] == "Weather: Sunny, 72°F"
        assert formatted["is_error"] is False

    def test_format_error_result(self):
        """Test formatting error tool result."""
        result = ToolResult(
            tool_use_id="tool_456",
            content="Error: Location not found",
            is_error=True,
        )

        formatted = format_tool_result(result)

        assert formatted["type"] == "tool_result"
        assert formatted["is_error"] is True


class TestFormatToolsForApi:
    """Tests for format_tools_for_api."""

    def test_format_empty_registry(self):
        """Test formatting empty registry."""
        registry = ToolRegistry()
        result = format_tools_for_api(registry)
        assert result == []

    def test_format_multiple_tools(self):
        """Test formatting multiple tools."""
        registry = ToolRegistry(
            tools=[
                Tool(
                    name="tool1",
                    description="First tool",
                    input_schema={"type": "object"},
                ),
                Tool(
                    name="tool2",
                    description="Second tool",
                    input_schema={"type": "object"},
                ),
            ]
        )

        result = format_tools_for_api(registry)

        assert len(result) == 2
        assert result[0]["name"] == "tool1"
        assert result[1]["name"] == "tool2"


class TestClaudeToolHandler:
    """Tests for ClaudeToolHandler."""

    @pytest.mark.asyncio
    async def test_execute_allowed(self):
        """Test tool execution when allowed."""

        async def mock_executor(**kwargs):
            return f"Result: {kwargs.get('x', 'none')}"

        handler = ClaudeToolHandler(
            executor={"test_tool": mock_executor},
            pre_hook=None,  # No hook = always allow
        )

        call = ToolCall(id="tool_1", name="test_tool", input={"x": "value"})
        result = await handler.execute(call)

        assert result.tool_use_id == "tool_1"
        assert result.content == "Result: value"
        assert result.is_error is False

    @pytest.mark.asyncio
    async def test_execute_denied_by_hook(self):
        """Test tool execution denied by pre-hook."""

        async def deny_hook(tool_call: ToolCall) -> ToolDecision:
            return ToolDecision.DENY

        handler = ClaudeToolHandler(
            executor={"test_tool": AsyncMock()},
            pre_hook=deny_hook,
        )

        call = ToolCall(id="tool_1", name="test_tool", input={})
        result = await handler.execute(call)

        assert result.is_error is True
        assert "denied" in result.content.lower()

    @pytest.mark.asyncio
    async def test_execute_ask_by_hook(self):
        """Test tool execution requires confirmation."""

        async def ask_hook(tool_call: ToolCall) -> ToolDecision:
            return ToolDecision.ASK

        handler = ClaudeToolHandler(
            executor={"test_tool": AsyncMock()},
            pre_hook=ask_hook,
        )

        call = ToolCall(id="tool_1", name="test_tool", input={})
        result = await handler.execute(call)

        assert result.is_error is True
        assert "confirmation" in result.content.lower()

    @pytest.mark.asyncio
    async def test_execute_tool_not_found(self):
        """Test execution of unknown tool."""
        handler = ClaudeToolHandler(executor={})

        call = ToolCall(id="tool_1", name="unknown_tool", input={})
        result = await handler.execute(call)

        assert result.is_error is True
        assert "not found" in result.content.lower()

    @pytest.mark.asyncio
    async def test_execute_tool_raises_exception(self):
        """Test handling of tool execution errors."""

        async def failing_executor(**kwargs):
            raise ValueError("Something went wrong")

        handler = ClaudeToolHandler(executor={"fail_tool": failing_executor})

        call = ToolCall(id="tool_1", name="fail_tool", input={})
        result = await handler.execute(call)

        assert result.is_error is True
        assert "error" in result.content.lower()

    @pytest.mark.asyncio
    async def test_process_tool_calls(self):
        """Test processing multiple tool calls."""

        async def echo_executor(**kwargs):
            return kwargs.get("msg", "")

        handler = ClaudeToolHandler(executor={"echo": echo_executor})

        calls = [
            ToolCall(id="t1", name="echo", input={"msg": "hello"}),
            ToolCall(id="t2", name="echo", input={"msg": "world"}),
        ]
        results = await handler.process_tool_calls(calls)

        assert len(results) == 2
        assert results[0].content == "hello"
        assert results[1].content == "world"

    @pytest.mark.asyncio
    async def test_check_permission_no_hook(self):
        """Test permission check with no hook returns ALLOW."""
        handler = ClaudeToolHandler()
        call = ToolCall(id="t1", name="test", input={})

        decision = await handler.check_permission(call)

        assert decision == ToolDecision.ALLOW

    @pytest.mark.asyncio
    async def test_check_permission_with_hook(self):
        """Test permission check delegates to hook."""

        async def custom_hook(tool_call: ToolCall) -> ToolDecision:
            if tool_call.name == "dangerous":
                return ToolDecision.DENY
            return ToolDecision.ALLOW

        handler = ClaudeToolHandler(pre_hook=custom_hook)

        safe_call = ToolCall(id="t1", name="safe", input={})
        dangerous_call = ToolCall(id="t2", name="dangerous", input={})

        assert await handler.check_permission(safe_call) == ToolDecision.ALLOW
        assert await handler.check_permission(dangerous_call) == ToolDecision.DENY
