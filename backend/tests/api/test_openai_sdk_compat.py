"""Tests verifying OpenAI Python SDK compatibility.

These tests verify that the OpenAI Python SDK can successfully communicate
with Agent Hub's OpenAI-compatible endpoints.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.adapters.base import CompletionResult, StreamEvent
from app.main import app
from app.services.api_key_auth import AuthenticatedKey


@pytest.fixture
def client():
    """Test client for the FastAPI app."""
    return TestClient(app)


@pytest.fixture
def mock_auth_bypass():
    """Bypass API key authentication for SDK compat tests."""
    with patch("app.services.api_key_auth.validate_api_key") as mock_validate:
        # Return None - anonymous access is allowed
        mock_validate.return_value = None
        yield mock_validate


class TestOpenAIPythonSDKCompat:
    """Tests that verify OpenAI Python SDK can work with our endpoints.

    These tests simulate what the openai Python SDK does internally.
    """

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

    def test_sdk_creates_chat_completion(self, client, mock_claude_adapter):
        """Test: from openai import OpenAI; client.chat.completions.create()

        The OpenAI SDK sends requests in this exact format.
        Note: No Authorization header - testing SDK format, not auth.
        """
        # Simulate what openai SDK sends (anonymous access)
        response = client.post(
            "/api/v1/chat/completions",
            headers={
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-4",
                "messages": [
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": "Say hello"},
                ],
                "temperature": 1.0,
                "max_tokens": 1024,
                "stream": False,
            },
        )

        assert response.status_code == 200
        data = response.json()

        # Verify response matches OpenAI SDK expectations
        assert "id" in data
        assert data["id"].startswith("chatcmpl-")
        assert data["object"] == "chat.completion"
        assert "created" in data
        assert isinstance(data["created"], int)
        assert "model" in data
        assert "choices" in data
        assert len(data["choices"]) == 1

        choice = data["choices"][0]
        assert "index" in choice
        assert choice["index"] == 0
        assert "message" in choice
        assert choice["message"]["role"] == "assistant"
        assert "content" in choice["message"]
        assert "finish_reason" in choice

        assert "usage" in data
        assert "prompt_tokens" in data["usage"]
        assert "completion_tokens" in data["usage"]
        assert "total_tokens" in data["usage"]

    def test_sdk_streams_chat_completion(self, client, mock_claude_adapter_stream):
        """Test: client.chat.completions.create(stream=True)

        The OpenAI SDK expects SSE format with specific structure.
        """
        response = client.post(
            "/api/v1/chat/completions",
            headers={
                "Authorization": "Bearer sk-test-key",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "Hello"}],
                "stream": True,
            },
        )

        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]

        # Parse SSE events
        events = []
        for line in response.text.strip().split("\n\n"):
            if line.startswith("data: ") and line != "data: [DONE]":
                import json as json_module

                data = json_module.loads(line[6:])
                events.append(data)

        # First chunk should have role
        assert events[0]["choices"][0]["delta"].get("role") == "assistant"

        # All chunks should have proper structure
        for event in events:
            assert "id" in event
            assert event["id"].startswith("chatcmpl-")
            assert event["object"] == "chat.completion.chunk"
            assert "created" in event
            assert "model" in event
            assert "choices" in event

        # Last chunk with content should have finish_reason
        last_event = events[-1]
        # The second-to-last or last should have finish_reason
        has_finish = any(
            e["choices"][0].get("finish_reason") is not None for e in events
        )
        assert has_finish

    def test_sdk_lists_models(self, client):
        """Test: client.models.list()

        The OpenAI SDK expects a list response with specific format.
        """
        response = client.get(
            "/api/v1/models",
            headers={"Authorization": "Bearer sk-test-key"},
        )

        assert response.status_code == 200
        data = response.json()

        assert data["object"] == "list"
        assert "data" in data
        assert isinstance(data["data"], list)
        assert len(data["data"]) > 0

        # Each model should have required fields
        for model in data["data"]:
            assert "id" in model
            assert model["object"] == "model"
            assert "created" in model
            assert "owned_by" in model

    def test_sdk_retrieves_model(self, client):
        """Test: client.models.retrieve('gpt-4')

        The OpenAI SDK expects a single model object.
        """
        response = client.get(
            "/api/v1/models/gpt-4",
            headers={"Authorization": "Bearer sk-test-key"},
        )

        assert response.status_code == 200
        data = response.json()

        assert data["id"] == "gpt-4"
        assert data["object"] == "model"
        assert "created" in data
        assert "owned_by" in data

    def test_sdk_handles_error_format(self, client):
        """Test: SDK expects specific error format

        OpenAI SDK parses errors with {"error": {"message", "type", "code"}}
        """
        response = client.get(
            "/api/v1/models/nonexistent-model",
            headers={"Authorization": "Bearer sk-test-key"},
        )

        assert response.status_code == 404
        data = response.json()

        # OpenAI SDK expects this structure
        assert "detail" in data
        assert "error" in data["detail"]
        assert "message" in data["detail"]["error"]
        assert "type" in data["detail"]["error"]
        assert "code" in data["detail"]["error"]

    def test_sdk_with_function_calling(self, client, mock_claude_adapter):
        """Test: client.chat.completions.create(tools=[...])

        The OpenAI SDK sends function definitions in tools array.
        """
        response = client.post(
            "/api/v1/chat/completions",
            headers={
                "Authorization": "Bearer sk-test-key",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "What's the weather?"}],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "description": "Get weather for a location",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "location": {"type": "string"},
                                },
                                "required": ["location"],
                            },
                        },
                    },
                ],
                "tool_choice": "auto",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "choices" in data
        assert data["choices"][0]["message"]["role"] == "assistant"

    def test_sdk_with_legacy_functions(self, client, mock_claude_adapter):
        """Test: SDK legacy functions parameter (deprecated but still used)"""
        response = client.post(
            "/api/v1/chat/completions",
            headers={
                "Authorization": "Bearer sk-test-key",
            },
            json={
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "Calculate 2+2"}],
                "functions": [
                    {
                        "name": "calculator",
                        "description": "Perform calculations",
                        "parameters": {"type": "object", "properties": {}},
                    },
                ],
            },
        )

        assert response.status_code == 200
