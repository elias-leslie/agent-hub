"""Tests for OpenAI-compatible API endpoints."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.adapters.base import (
    AuthenticationError,
    CompletionResult,
    ProviderError,
    RateLimitError,
    StreamEvent,
)
from app.api.openai_compat import (
    MODEL_MAPPING,
    _convert_messages,
    _convert_tools_to_prompt,
    _map_finish_reason,
    _resolve_model,
    AVAILABLE_MODELS,
    OpenAIMessage,
    OpenAITool,
    OpenAIFunction,
    OpenAIFunctionCall,
    OpenAIToolCall,
)
from app.main import app


@pytest.fixture
def client():
    """Test client for the FastAPI app."""
    return TestClient(app)


class TestModelMapping:
    """Tests for model mapping functions."""

    def test_resolve_gpt4_to_sonnet(self):
        """GPT-4 models map to Claude Sonnet."""
        for model in ["gpt-4", "gpt-4-turbo", "gpt-4-turbo-preview", "gpt-4o"]:
            actual, provider = _resolve_model(model)
            assert actual == "claude-sonnet-4-5-20250514", f"Failed for {model}"
            assert provider == "claude"

    def test_resolve_gpt35_to_haiku(self):
        """GPT-3.5 models map to Claude Haiku."""
        for model in ["gpt-3.5-turbo", "gpt-3.5-turbo-16k", "gpt-4o-mini"]:
            actual, provider = _resolve_model(model)
            assert actual == "claude-haiku-4-5-20250514", f"Failed for {model}"
            assert provider == "claude"

    def test_resolve_native_claude(self):
        """Native Claude models pass through."""
        actual, provider = _resolve_model("claude-sonnet-4-5")
        assert actual == "claude-sonnet-4-5-20250514"
        assert provider == "claude"

    def test_resolve_gemini(self):
        """Gemini models resolve correctly."""
        actual, provider = _resolve_model("gemini-3-flash")
        assert actual == "gemini-3-flash-preview"
        assert provider == "gemini"

    def test_resolve_unknown_model(self):
        """Unknown models pass through with claude provider."""
        actual, provider = _resolve_model("unknown-model-xyz")
        assert actual == "unknown-model-xyz"
        assert provider == "claude"


class TestMessageConversion:
    """Tests for message conversion."""

    def test_convert_simple_messages(self):
        """Convert simple user/assistant messages."""
        messages = [
            OpenAIMessage(role="user", content="Hello"),
            OpenAIMessage(role="assistant", content="Hi there"),
        ]
        result = _convert_messages(messages)
        assert len(result) == 2
        assert result[0].role == "user"
        assert result[0].content == "Hello"
        assert result[1].role == "assistant"
        assert result[1].content == "Hi there"

    def test_convert_system_message(self):
        """Convert system message."""
        messages = [
            OpenAIMessage(role="system", content="You are helpful"),
            OpenAIMessage(role="user", content="Hi"),
        ]
        result = _convert_messages(messages)
        assert result[0].role == "system"
        assert result[0].content == "You are helpful"

    def test_convert_tool_result(self):
        """Convert tool result message."""
        messages = [
            OpenAIMessage(
                role="tool",
                content='{"result": "42"}',
                tool_call_id="call_123",
            ),
        ]
        result = _convert_messages(messages)
        assert result[0].role == "user"
        assert "Tool result (call_123)" in result[0].content

    def test_convert_assistant_with_tool_calls(self):
        """Convert assistant message with tool calls."""
        messages = [
            OpenAIMessage(
                role="assistant",
                content="Let me calculate",
                tool_calls=[
                    OpenAIToolCall(
                        id="call_123",
                        type="function",
                        function=OpenAIFunctionCall(
                            name="calculator",
                            arguments='{"x": 1, "y": 2}',
                        ),
                    ),
                ],
            ),
        ]
        result = _convert_messages(messages)
        assert result[0].role == "assistant"
        assert "calculator" in result[0].content
        assert '{"x": 1, "y": 2}' in result[0].content

    def test_convert_legacy_function_call(self):
        """Convert legacy function_call format."""
        messages = [
            OpenAIMessage(
                role="assistant",
                content="Calling function",
                function_call=OpenAIFunctionCall(
                    name="get_weather",
                    arguments='{"city": "NYC"}',
                ),
            ),
        ]
        result = _convert_messages(messages)
        assert "get_weather" in result[0].content


class TestToolConversion:
    """Tests for tool conversion to prompts."""

    def test_convert_tools_none(self):
        """No tools returns None."""
        assert _convert_tools_to_prompt(None) is None
        assert _convert_tools_to_prompt([]) is None

    def test_convert_tools_basic(self):
        """Convert basic tool definitions."""
        tools = [
            OpenAITool(
                type="function",
                function=OpenAIFunction(
                    name="get_weather",
                    description="Get weather for a city",
                    parameters={"type": "object", "properties": {"city": {"type": "string"}}},
                ),
            ),
        ]
        result = _convert_tools_to_prompt(tools)
        assert "get_weather" in result
        assert "Get weather for a city" in result


class TestFinishReasonMapping:
    """Tests for finish reason mapping."""

    def test_map_end_turn(self):
        assert _map_finish_reason("end_turn") == "stop"

    def test_map_stop_sequence(self):
        assert _map_finish_reason("stop_sequence") == "stop"

    def test_map_max_tokens(self):
        assert _map_finish_reason("max_tokens") == "length"

    def test_map_tool_use(self):
        assert _map_finish_reason("tool_use") == "tool_calls"

    def test_map_none(self):
        assert _map_finish_reason(None) == "stop"

    def test_map_unknown(self):
        assert _map_finish_reason("unknown_reason") == "stop"


class TestChatCompletionsEndpoint:
    """Tests for POST /api/v1/chat/completions."""

    @pytest.fixture
    def mock_claude_adapter(self):
        """Mock ClaudeAdapter."""
        with patch("app.api.openai_compat.ClaudeAdapter") as mock:
            adapter = AsyncMock()
            adapter.complete = AsyncMock(
                return_value=CompletionResult(
                    content="Hello from Claude!",
                    model="claude-sonnet-4-5-20250514",
                    provider="claude",
                    input_tokens=10,
                    output_tokens=5,
                    finish_reason="end_turn",
                )
            )
            mock.return_value = adapter
            yield mock

    def test_chat_completion_gpt4(self, client, mock_claude_adapter):
        """Test GPT-4 request routed to Claude Sonnet."""
        response = client.post(
            "/api/v1/chat/completions",
            json={
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["object"] == "chat.completion"
        assert data["model"] == "gpt-4"  # Display model
        assert data["choices"][0]["message"]["role"] == "assistant"
        assert data["choices"][0]["message"]["content"] == "Hello from Claude!"
        assert data["choices"][0]["finish_reason"] == "stop"
        assert data["usage"]["prompt_tokens"] == 10
        assert data["usage"]["completion_tokens"] == 5
        assert data["usage"]["total_tokens"] == 15

    def test_chat_completion_gpt35(self, client, mock_claude_adapter):
        """Test GPT-3.5 request routed to Claude Haiku."""
        response = client.post(
            "/api/v1/chat/completions",
            json={
                "model": "gpt-3.5-turbo",
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )

        assert response.status_code == 200
        # Verify adapter called with haiku model
        call_kwargs = mock_claude_adapter.return_value.complete.call_args.kwargs
        assert "haiku" in call_kwargs["model"]

    def test_chat_completion_with_system_message(self, client, mock_claude_adapter):
        """Test chat completion with system message."""
        response = client.post(
            "/api/v1/chat/completions",
            json={
                "model": "gpt-4",
                "messages": [
                    {"role": "system", "content": "You are helpful"},
                    {"role": "user", "content": "Hello"},
                ],
            },
        )

        assert response.status_code == 200
        # Verify messages were passed correctly
        call_kwargs = mock_claude_adapter.return_value.complete.call_args.kwargs
        messages = call_kwargs["messages"]
        assert any(m.role == "system" for m in messages)

    def test_chat_completion_with_custom_params(self, client, mock_claude_adapter):
        """Test chat completion with custom parameters."""
        response = client.post(
            "/api/v1/chat/completions",
            json={
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "Hello"}],
                "max_tokens": 1000,
                "temperature": 0.5,
            },
        )

        assert response.status_code == 200
        call_kwargs = mock_claude_adapter.return_value.complete.call_args.kwargs
        assert call_kwargs["max_tokens"] == 1000
        assert call_kwargs["temperature"] == 0.5

    def test_chat_completion_rate_limit_error(self, client):
        """Test rate limit error returns OpenAI format."""
        with patch("app.api.openai_compat.ClaudeAdapter") as mock:
            adapter = AsyncMock()
            adapter.complete = AsyncMock(side_effect=RateLimitError("claude", retry_after=30))
            mock.return_value = adapter

            response = client.post(
                "/api/v1/chat/completions",
                json={
                    "model": "gpt-4",
                    "messages": [{"role": "user", "content": "Hi"}],
                },
            )

            assert response.status_code == 429
            assert "Retry-After" in response.headers
            data = response.json()
            assert "error" in data["detail"]
            assert data["detail"]["error"]["type"] == "rate_limit_error"

    def test_chat_completion_auth_error(self, client):
        """Test authentication error returns OpenAI format."""
        with patch("app.api.openai_compat.ClaudeAdapter") as mock:
            adapter = AsyncMock()
            adapter.complete = AsyncMock(side_effect=AuthenticationError("claude"))
            mock.return_value = adapter

            response = client.post(
                "/api/v1/chat/completions",
                json={
                    "model": "gpt-4",
                    "messages": [{"role": "user", "content": "Hi"}],
                },
            )

            assert response.status_code == 401
            data = response.json()
            assert "error" in data["detail"]
            assert data["detail"]["error"]["type"] == "authentication_error"

    def test_chat_completion_missing_model(self, client):
        """Test validation error for missing model."""
        response = client.post(
            "/api/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "Hi"}]},
        )
        assert response.status_code == 422

    def test_chat_completion_missing_messages(self, client):
        """Test validation error for missing messages."""
        response = client.post(
            "/api/v1/chat/completions",
            json={"model": "gpt-4"},
        )
        assert response.status_code == 422

    def test_chat_completion_with_tools(self, client, mock_claude_adapter):
        """Test chat completion with tool definitions."""
        response = client.post(
            "/api/v1/chat/completions",
            json={
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "What's the weather?"}],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "description": "Get current weather",
                            "parameters": {"type": "object", "properties": {}},
                        },
                    },
                ],
            },
        )

        assert response.status_code == 200
        # Tools should be converted to system prompt
        call_kwargs = mock_claude_adapter.return_value.complete.call_args.kwargs
        messages = call_kwargs["messages"]
        # First message should have tool info
        assert any("get_weather" in m.content for m in messages if m.role == "system")

    def test_chat_completion_response_id_format(self, client, mock_claude_adapter):
        """Test that response ID follows OpenAI format."""
        response = client.post(
            "/api/v1/chat/completions",
            json={
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"].startswith("chatcmpl-")
        assert len(data["id"]) > 10


class TestChatCompletionsStreaming:
    """Tests for streaming chat completions."""

    @pytest.fixture
    def mock_claude_adapter_stream(self):
        """Mock ClaudeAdapter with streaming."""
        with patch("app.api.openai_compat.ClaudeAdapter") as mock:
            adapter = AsyncMock()

            async def mock_stream(*args, **kwargs):
                yield StreamEvent(type="content", content="Hello")
                yield StreamEvent(type="content", content=" world")
                yield StreamEvent(
                    type="done",
                    input_tokens=10,
                    output_tokens=2,
                    finish_reason="end_turn",
                )

            adapter.stream = mock_stream
            mock.return_value = adapter
            yield mock

    def test_streaming_response_format(self, client, mock_claude_adapter_stream):
        """Test streaming returns SSE format."""
        response = client.post(
            "/api/v1/chat/completions",
            json={
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "Hello"}],
                "stream": True,
            },
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

        # Parse SSE events
        lines = response.text.strip().split("\n\n")
        assert len(lines) >= 3  # Initial role, content chunks, final, [DONE]

        # Check first chunk has role
        first_data = lines[0].replace("data: ", "")
        assert "assistant" in first_data

        # Check last line is [DONE]
        assert "[DONE]" in lines[-1]


class TestModelsEndpoint:
    """Tests for /api/v1/models endpoint."""

    def test_list_models(self, client):
        """Test listing all models."""
        response = client.get("/api/v1/models")

        assert response.status_code == 200
        data = response.json()
        assert data["object"] == "list"
        assert len(data["data"]) > 0

        # Check model format
        model = data["data"][0]
        assert "id" in model
        assert model["object"] == "model"
        assert "created" in model
        assert "owned_by" in model

    def test_list_models_includes_gpt_aliases(self, client):
        """Test that GPT model aliases are included."""
        response = client.get("/api/v1/models")

        data = response.json()
        model_ids = [m["id"] for m in data["data"]]

        assert "gpt-4" in model_ids
        assert "gpt-3.5-turbo" in model_ids

    def test_list_models_includes_claude(self, client):
        """Test that native Claude models are included."""
        response = client.get("/api/v1/models")

        data = response.json()
        model_ids = [m["id"] for m in data["data"]]

        assert "claude-sonnet-4-5" in model_ids
        assert "claude-haiku-4-5" in model_ids

    def test_list_models_includes_gemini(self, client):
        """Test that Gemini models are included."""
        response = client.get("/api/v1/models")

        data = response.json()
        model_ids = [m["id"] for m in data["data"]]

        assert "gemini-3-flash" in model_ids
        assert "gemini-3-pro" in model_ids

    def test_get_model(self, client):
        """Test getting a specific model."""
        response = client.get("/api/v1/models/gpt-4")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "gpt-4"
        assert data["object"] == "model"
        assert data["owned_by"] == "agent-hub"
        assert data["context_length"] == 200000
        assert data["supports_vision"] is True

    def test_get_model_not_found(self, client):
        """Test getting non-existent model."""
        response = client.get("/api/v1/models/nonexistent-model")

        assert response.status_code == 404
        data = response.json()
        assert "error" in data["detail"]
        assert data["detail"]["error"]["code"] == "model_not_found"

    def test_model_capabilities(self, client):
        """Test that model capabilities are included."""
        response = client.get("/api/v1/models/claude-sonnet-4-5")

        assert response.status_code == 200
        data = response.json()
        assert "context_length" in data
        assert "supports_vision" in data
        assert "supports_function_calling" in data
