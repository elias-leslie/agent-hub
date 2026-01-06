"""Tests for Gemini tool calling support."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from google.genai import types

from app.services.tools.base import (
    Tool,
    ToolCall,
    ToolDecision,
    ToolRegistry,
    ToolResult,
)
from app.services.tools.gemini_tools import (
    GeminiToolHandler,
    format_function_response,
    format_function_response_with_name,
    format_tools_for_api,
    parse_function_calls,
)


class TestParseFunctionCalls:
    """Tests for parse_function_calls."""

    def test_parse_text_only(self):
        """Test parsing response with only text."""
        part = MagicMock(spec=types.Part)
        part.text = "Hello, world!"
        part.function_call = None

        result = parse_function_calls([part])

        assert result.text_content == "Hello, world!"
        assert len(result.tool_calls) == 0

    def test_parse_function_call_only(self):
        """Test parsing response with only function call."""
        fc = MagicMock()
        fc.id = "call_123"
        fc.name = "get_weather"
        fc.args = {"location": "NYC"}

        part = MagicMock(spec=types.Part)
        part.text = None
        part.function_call = fc

        result = parse_function_calls([part])

        assert result.text_content == ""
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].id == "call_123"
        assert result.tool_calls[0].name == "get_weather"
        assert result.tool_calls[0].input == {"location": "NYC"}

    def test_parse_function_call_without_id(self):
        """Test parsing function call without id (uses name as fallback)."""
        fc = MagicMock()
        fc.id = None
        fc.name = "get_weather"
        fc.args = {"location": "Paris"}

        part = MagicMock(spec=types.Part)
        part.text = None
        part.function_call = fc

        result = parse_function_calls([part])

        # Should use name as fallback id
        assert result.tool_calls[0].id == "get_weather"

    def test_parse_mixed_content(self):
        """Test parsing response with text and function call."""
        text_part = MagicMock(spec=types.Part)
        text_part.text = "Let me check that for you."
        text_part.function_call = None

        fc = MagicMock()
        fc.id = "call_456"
        fc.name = "search"
        fc.args = {"query": "weather"}

        func_part = MagicMock(spec=types.Part)
        func_part.text = None
        func_part.function_call = fc

        result = parse_function_calls([text_part, func_part])

        assert result.text_content == "Let me check that for you."
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "search"

    def test_parse_multiple_function_calls(self):
        """Test parsing response with multiple function calls."""
        parts = []
        for i, name in enumerate(["func1", "func2", "func3"]):
            fc = MagicMock()
            fc.id = f"call_{i}"
            fc.name = name
            fc.args = {"arg": i}

            part = MagicMock(spec=types.Part)
            part.text = None
            part.function_call = fc
            parts.append(part)

        result = parse_function_calls(parts)

        assert len(result.tool_calls) == 3
        assert [tc.name for tc in result.tool_calls] == ["func1", "func2", "func3"]


class TestFormatFunctionResponse:
    """Tests for format_function_response."""

    def test_format_success_response(self):
        """Test formatting successful function response."""
        result = ToolResult(
            tool_use_id="call_123",
            content="Weather: Sunny, 72°F",
            is_error=False,
        )

        formatted = format_function_response(result)

        assert isinstance(formatted, types.FunctionResponse)
        assert formatted.id == "call_123"
        assert formatted.response["result"] == "Weather: Sunny, 72°F"
        assert formatted.response["is_error"] is False

    def test_format_error_response(self):
        """Test formatting error function response."""
        result = ToolResult(
            tool_use_id="call_456",
            content="Error: Location not found",
            is_error=True,
        )

        formatted = format_function_response(result)

        assert formatted.response["is_error"] is True

    def test_format_with_explicit_name(self):
        """Test formatting with explicit function name."""
        result = ToolResult(
            tool_use_id="call_789",
            content="Done",
            is_error=False,
        )

        formatted = format_function_response_with_name(result, "my_function")

        assert formatted.name == "my_function"
        assert formatted.id == "call_789"


class TestFormatToolsForApi:
    """Tests for format_tools_for_api."""

    def test_format_empty_registry(self):
        """Test formatting empty registry."""
        registry = ToolRegistry()
        result = format_tools_for_api(registry)
        assert result == []

    def test_format_single_tool(self):
        """Test formatting single tool."""
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

        result = format_tools_for_api(registry)

        assert len(result) == 1
        assert isinstance(result[0], types.Tool)
        assert len(result[0].function_declarations) == 1
        assert result[0].function_declarations[0].name == "get_weather"

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

        # All tools should be in one Tool object with multiple declarations
        assert len(result) == 1
        assert len(result[0].function_declarations) == 2


class TestGeminiToolHandler:
    """Tests for GeminiToolHandler."""

    @pytest.mark.asyncio
    async def test_execute_allowed(self):
        """Test function execution when allowed."""

        async def mock_executor(**kwargs):
            return f"Result: {kwargs.get('x', 'none')}"

        handler = GeminiToolHandler(
            executor={"test_func": mock_executor},
            pre_hook=None,
        )

        call = ToolCall(id="call_1", name="test_func", input={"x": "value"})
        result = await handler.execute(call)

        assert result.tool_use_id == "call_1"
        assert result.content == "Result: value"
        assert result.is_error is False

    @pytest.mark.asyncio
    async def test_execute_denied_by_hook(self):
        """Test function execution denied by pre-hook."""

        async def deny_hook(tool_call: ToolCall) -> ToolDecision:
            return ToolDecision.DENY

        handler = GeminiToolHandler(
            executor={"test_func": AsyncMock()},
            pre_hook=deny_hook,
        )

        call = ToolCall(id="call_1", name="test_func", input={})
        result = await handler.execute(call)

        assert result.is_error is True
        assert "denied" in result.content.lower()

    @pytest.mark.asyncio
    async def test_execute_ask_by_hook(self):
        """Test function execution requires confirmation."""

        async def ask_hook(tool_call: ToolCall) -> ToolDecision:
            return ToolDecision.ASK

        handler = GeminiToolHandler(
            executor={"test_func": AsyncMock()},
            pre_hook=ask_hook,
        )

        call = ToolCall(id="call_1", name="test_func", input={})
        result = await handler.execute(call)

        assert result.is_error is True
        assert "confirmation" in result.content.lower()

    @pytest.mark.asyncio
    async def test_execute_function_not_found(self):
        """Test execution of unknown function."""
        handler = GeminiToolHandler(executor={})

        call = ToolCall(id="call_1", name="unknown_func", input={})
        result = await handler.execute(call)

        assert result.is_error is True
        assert "not found" in result.content.lower()

    @pytest.mark.asyncio
    async def test_execute_function_raises_exception(self):
        """Test handling of function execution errors."""

        async def failing_executor(**kwargs):
            raise ValueError("Something went wrong")

        handler = GeminiToolHandler(executor={"fail_func": failing_executor})

        call = ToolCall(id="call_1", name="fail_func", input={})
        result = await handler.execute(call)

        assert result.is_error is True
        assert "error" in result.content.lower()

    @pytest.mark.asyncio
    async def test_process_function_calls(self):
        """Test processing multiple function calls."""

        async def echo_executor(**kwargs):
            return kwargs.get("msg", "")

        handler = GeminiToolHandler(executor={"echo": echo_executor})

        calls = [
            ToolCall(id="c1", name="echo", input={"msg": "hello"}),
            ToolCall(id="c2", name="echo", input={"msg": "world"}),
        ]
        results = await handler.process_function_calls(calls)

        assert len(results) == 2
        assert results[0][0].content == "hello"
        assert results[0][1] == "echo"
        assert results[1][0].content == "world"
        assert results[1][1] == "echo"

    @pytest.mark.asyncio
    async def test_check_permission_no_hook(self):
        """Test permission check with no hook returns ALLOW."""
        handler = GeminiToolHandler()
        call = ToolCall(id="c1", name="test", input={})

        decision = await handler.check_permission(call)

        assert decision == ToolDecision.ALLOW

    @pytest.mark.asyncio
    async def test_check_permission_with_hook(self):
        """Test permission check delegates to hook."""

        async def custom_hook(tool_call: ToolCall) -> ToolDecision:
            if tool_call.name == "dangerous":
                return ToolDecision.DENY
            return ToolDecision.ALLOW

        handler = GeminiToolHandler(pre_hook=custom_hook)

        safe_call = ToolCall(id="c1", name="safe", input={})
        dangerous_call = ToolCall(id="c2", name="dangerous", input={})

        assert await handler.check_permission(safe_call) == ToolDecision.ALLOW
        assert await handler.check_permission(dangerous_call) == ToolDecision.DENY
