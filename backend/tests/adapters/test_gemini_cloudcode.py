"""Tests for the CloudCode PA client (consumer OAuth via cloudcode-pa.googleapis.com)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.adapters.base import Message
from app.adapters.gemini_cloudcode import (
    CloudCodeClient,
    build_cloudcode_tools,
    build_generation_config,
    cloudcode_complete,
    cloudcode_stream,
    convert_messages_for_cloudcode,
    parse_cloudcode_response,
)

# ---------------------------------------------------------------------------
# Message conversion
# ---------------------------------------------------------------------------


class TestConvertMessages:
    def test_user_message(self):
        msgs = [Message(role="user", content="hello")]
        sys_inst, contents = convert_messages_for_cloudcode(msgs)
        assert sys_inst is None
        assert contents == [{"role": "user", "parts": [{"text": "hello"}]}]

    def test_system_message_extracted(self):
        msgs = [
            Message(role="system", content="Be helpful"),
            Message(role="user", content="hi"),
        ]
        sys_inst, contents = convert_messages_for_cloudcode(msgs)
        assert sys_inst == {"parts": [{"text": "Be helpful"}]}
        assert len(contents) == 1
        assert contents[0]["role"] == "user"

    def test_assistant_uses_model_role(self):
        msgs = [
            Message(role="user", content="hi"),
            Message(role="assistant", content="hey"),
        ]
        _, contents = convert_messages_for_cloudcode(msgs)
        assert contents[1]["role"] == "model"

    def test_image_content(self):
        msgs = [
            Message(
                role="user",
                content=[
                    {"type": "text", "text": "describe this"},
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": "AAAA",
                        },
                    },
                ],
            ),
        ]
        _, contents = convert_messages_for_cloudcode(msgs)
        parts = contents[0]["parts"]
        assert parts[0] == {"text": "describe this"}
        assert parts[1] == {"inlineData": {"mimeType": "image/png", "data": "AAAA"}}


# ---------------------------------------------------------------------------
# Tool conversion
# ---------------------------------------------------------------------------


class TestBuildCloudcodeTools:
    def test_basic_tool(self):
        tools = [
            {
                "name": "get_weather",
                "description": "Get weather",
                "input_schema": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            },
        ]
        result = build_cloudcode_tools(tools)
        assert len(result) == 1
        decls = result[0]["functionDeclarations"]
        assert decls[0]["name"] == "get_weather"
        # Types should be uppercased for Gemini
        assert decls[0]["parameters"]["type"] == "OBJECT"
        assert decls[0]["parameters"]["properties"]["city"]["type"] == "STRING"

    def test_parameters_key_fallback(self):
        tools = [
            {
                "name": "t",
                "description": "d",
                "parameters": {"type": "object", "properties": {}},
            },
        ]
        result = build_cloudcode_tools(tools)
        assert result[0]["functionDeclarations"][0]["parameters"]["type"] == "OBJECT"


# ---------------------------------------------------------------------------
# Generation config
# ---------------------------------------------------------------------------


class TestBuildGenerationConfig:
    def test_empty_defaults(self):
        assert build_generation_config() is None

    def test_temperature(self):
        cfg = build_generation_config(temperature=0.5)
        assert cfg == {"temperature": 0.5}

    def test_max_tokens(self):
        cfg = build_generation_config(max_tokens=1024)
        assert cfg == {"maxOutputTokens": 1024}

    def test_thinking_gemini3(self):
        cfg = build_generation_config(
            model="gemini-3-flash-preview", thinking_level="high",
        )
        assert cfg is not None
        assert cfg["thinkingConfig"]["includeThoughts"] is True
        assert cfg["thinkingConfig"]["thinkingLevel"] == "HIGH"

    def test_thinking_ignored_non_gemini3(self):
        cfg = build_generation_config(
            model="gemini-2.5-flash", thinking_level="high",
        )
        # No thinkingConfig for non-gemini-3 models
        assert cfg is None


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


class TestParseCloudcodeResponse:
    def test_text_response(self):
        data = {
            "response": {
                "candidates": [
                    {
                        "content": {
                            "role": "model",
                            "parts": [{"text": "Hello world"}],
                        },
                        "finishReason": "STOP",
                    },
                ],
                "usageMetadata": {
                    "promptTokenCount": 10,
                    "candidatesTokenCount": 5,
                },
            },
        }
        result = parse_cloudcode_response(data, "gemini-3-flash-preview", "gemini")
        assert result.content == "Hello world"
        assert result.finish_reason == "STOP"
        assert result.input_tokens == 10
        assert result.output_tokens == 5
        assert result.tool_calls is None

    def test_thinking_response(self):
        data = {
            "response": {
                "candidates": [
                    {
                        "content": {
                            "role": "model",
                            "parts": [
                                {"text": "thinking...", "thought": True},
                                {"text": "Answer"},
                            ],
                        },
                        "finishReason": "STOP",
                    },
                ],
                "usageMetadata": {
                    "promptTokenCount": 10,
                    "candidatesTokenCount": 5,
                    "thoughtsTokenCount": 20,
                },
            },
        }
        result = parse_cloudcode_response(data, "gemini-3-pro-preview", "gemini")
        assert result.content == "Answer"
        assert result.thinking_content == "thinking..."
        assert result.thinking_tokens == 20

    def test_tool_call_response(self):
        data = {
            "response": {
                "candidates": [
                    {
                        "content": {
                            "role": "model",
                            "parts": [
                                {
                                    "functionCall": {
                                        "name": "get_weather",
                                        "args": {"city": "Paris"},
                                        "id": "call_123",
                                    },
                                },
                            ],
                        },
                        "finishReason": "OTHER",
                    },
                ],
                "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5},
            },
        }
        result = parse_cloudcode_response(data, "gemini-3-flash-preview", "gemini")
        assert result.tool_calls is not None
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "get_weather"
        assert result.tool_calls[0].input == {"city": "Paris"}
        assert result.tool_calls[0].id == "call_123"

    def test_empty_candidates(self):
        data = {"response": {"candidates": []}}
        result = parse_cloudcode_response(data, "gemini-3-flash-preview", "gemini")
        assert result.content == ""
        assert result.tool_calls is None


# ---------------------------------------------------------------------------
# CloudCodeClient
# ---------------------------------------------------------------------------


class TestCloudCodeClient:
    def test_is_expired_none(self):
        client = CloudCodeClient("tok", None, "proj", expires_at=None)
        assert client.is_expired is False

    def test_is_expired_future(self):
        import time

        client = CloudCodeClient("tok", None, "proj", expires_at=time.time() + 300)
        assert client.is_expired is False

    def test_is_expired_past(self):
        client = CloudCodeClient("tok", None, "proj", expires_at=0.0)
        assert client.is_expired is True

    def test_headers_basic(self):
        client = CloudCodeClient("my_token", None, "proj")
        headers = client._headers()
        assert headers["Authorization"] == "Bearer my_token"
        assert "Accept" not in headers

    def test_headers_streaming(self):
        client = CloudCodeClient("my_token", None, "proj")
        headers = client._headers(streaming=True)
        assert headers["Accept"] == "text/event-stream"

    def test_build_request_body(self):
        client = CloudCodeClient("tok", None, "my-proj")
        body = client._build_request_body(
            model="gemini-3-flash-preview",
            contents=[{"role": "user", "parts": [{"text": "hi"}]}],
            system_instruction={"parts": [{"text": "be helpful"}]},
            generation_config={"maxOutputTokens": 100},
        )
        assert body["project"] == "my-proj"
        assert body["model"] == "gemini-3-flash-preview"
        assert body["request"]["contents"][0]["parts"][0]["text"] == "hi"
        assert body["request"]["systemInstruction"]["parts"][0]["text"] == "be helpful"
        assert body["request"]["generationConfig"]["maxOutputTokens"] == 100
        # Must NOT include extra fields that cause Google to misattribute quotas
        assert "requestType" not in body
        assert "userAgent" not in body
        assert "requestId" not in body

    @pytest.mark.asyncio
    async def test_generate_content_success(self):
        response_data = {
            "response": {
                "candidates": [
                    {
                        "content": {"role": "model", "parts": [{"text": "ok"}]},
                        "finishReason": "STOP",
                    },
                ],
            },
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = response_data

        with patch("app.adapters._gemini_cloudcode_client.httpx.AsyncClient") as mock_httpx:
            mock_client_instance = AsyncMock()
            mock_client_instance.post = AsyncMock(return_value=mock_resp)
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=None)
            mock_httpx.return_value = mock_client_instance

            client = CloudCodeClient("tok", None, "proj")
            result = await client.generate_content(
                model="gemini-3-flash-preview",
                contents=[{"role": "user", "parts": [{"text": "hi"}]}],
            )

        assert result["response"]["candidates"][0]["content"]["parts"][0]["text"] == "ok"

    @pytest.mark.asyncio
    async def test_generate_content_error(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.text = "Not Found"

        with patch("app.adapters._gemini_cloudcode_client.httpx.AsyncClient") as mock_httpx:
            mock_client_instance = AsyncMock()
            mock_client_instance.post = AsyncMock(return_value=mock_resp)
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=None)
            mock_httpx.return_value = mock_client_instance

            client = CloudCodeClient("tok", None, "proj")
            with pytest.raises(RuntimeError, match="HTTP 404"):
                await client.generate_content(
                    model="gemini-3-flash-preview",
                    contents=[{"role": "user", "parts": [{"text": "hi"}]}],
                )


# ---------------------------------------------------------------------------
# cloudcode_complete integration
# ---------------------------------------------------------------------------


class TestCloudcodeComplete:
    @pytest.mark.asyncio
    async def test_complete_success(self):
        response_data = {
            "response": {
                "candidates": [
                    {
                        "content": {"role": "model", "parts": [{"text": "Hello!"}]},
                        "finishReason": "STOP",
                    },
                ],
                "usageMetadata": {
                    "promptTokenCount": 10,
                    "candidatesTokenCount": 5,
                },
            },
        }

        client = CloudCodeClient("tok", None, "proj")
        client.generate_content = AsyncMock(return_value=response_data)

        result = await cloudcode_complete(
            client,
            [Message(role="user", content="Hi")],
            model="gemini-3-flash-preview",
        )

        assert result.content == "Hello!"
        assert result.input_tokens == 10
        assert result.output_tokens == 5
        assert result.provider == "gemini"

    @pytest.mark.asyncio
    async def test_complete_retries_on_429(self):
        """cloudcode_complete retries on 429 before raising ProviderError."""
        response_data = {
            "response": {
                "candidates": [
                    {
                        "content": {"role": "model", "parts": [{"text": "OK"}]},
                        "finishReason": "STOP",
                    },
                ],
                "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 2},
            },
        }

        call_count = 0

        async def flaky_generate(**kwargs: Any) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError(
                    'CloudCode generateContent HTTP 429: '
                    '"Your quota will reset after 0s."'
                )
            return response_data

        client = CloudCodeClient("tok", None, "proj")
        client.generate_content = flaky_generate  # type: ignore[assignment]

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await cloudcode_complete(
                client,
                [Message(role="user", content="Hi")],
                model="gemini-3-flash-preview",
            )

        assert result.content == "OK"
        assert call_count == 2


# ---------------------------------------------------------------------------
# cloudcode_stream integration
# ---------------------------------------------------------------------------


class TestCloudcodeStream:
    @pytest.mark.asyncio
    async def test_stream_text(self):
        chunks = [
            {"response": {"candidates": [{"content": {"role": "model", "parts": [{"text": "Hello"}]}}]}},
            {
                "response": {
                    "candidates": [
                        {
                            "content": {"role": "model", "parts": [{"text": " world"}]},
                            "finishReason": "STOP",
                        },
                    ],
                    "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5},
                },
            },
        ]

        async def mock_stream(*args: Any, **kwargs: Any):
            for chunk in chunks:
                yield chunk

        client = CloudCodeClient("tok", None, "proj")
        client.stream_generate_content = mock_stream  # type: ignore[assignment]

        events = []
        async for event in cloudcode_stream(
            client,
            [Message(role="user", content="Hi")],
            model="gemini-3-flash-preview",
        ):
            events.append(event)

        content_events = [e for e in events if e.type == "content"]
        assert len(content_events) == 2
        assert content_events[0].content == "Hello"
        assert content_events[1].content == " world"

        done_events = [e for e in events if e.type == "done"]
        assert len(done_events) == 1
        assert done_events[0].input_tokens == 10
        assert done_events[0].output_tokens == 5

    @pytest.mark.asyncio
    async def test_stream_tool_use(self):
        chunks = [
            {
                "response": {
                    "candidates": [
                        {
                            "content": {
                                "role": "model",
                                "parts": [
                                    {
                                        "functionCall": {
                                            "name": "read_file",
                                            "args": {"path": "/tmp/f.txt"},
                                            "id": "call_1",
                                        },
                                    },
                                ],
                            },
                            "finishReason": "OTHER",
                        },
                    ],
                    "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5},
                },
            },
        ]

        async def mock_stream(*args: Any, **kwargs: Any):
            for chunk in chunks:
                yield chunk

        client = CloudCodeClient("tok", None, "proj")
        client.stream_generate_content = mock_stream  # type: ignore[assignment]

        events = []
        async for event in cloudcode_stream(
            client,
            [Message(role="user", content="read /tmp/f.txt")],
            model="gemini-3-flash-preview",
        ):
            events.append(event)

        tool_events = [e for e in events if e.type == "tool_use"]
        assert len(tool_events) == 1
        assert tool_events[0].tool_name == "read_file"
        assert tool_events[0].tool_input == {"path": "/tmp/f.txt"}


# ---------------------------------------------------------------------------
# GeminiAdapter OAuth mode integration
# ---------------------------------------------------------------------------


class TestGeminiAdapterOAuthMode:
    """Test that GeminiAdapter routes to CloudCode when in oauth mode."""

    @pytest.mark.asyncio
    async def test_complete_routes_to_cloudcode(self):
        """When auth_mode=oauth, complete() uses cloudcode_complete."""
        response_data = {
            "response": {
                "candidates": [
                    {
                        "content": {"role": "model", "parts": [{"text": "OAuth reply"}]},
                        "finishReason": "STOP",
                    },
                ],
                "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5},
            },
        }

        with (
            patch("app.adapters.gemini.resolve_oauth_data") as mock_oauth,
            patch("app.adapters.gemini.resolve_api_key", return_value=None),
            patch("app.adapters.gemini.get_gemini_auth_preference", return_value="oauth"),
        ):
            mock_oauth.return_value = {
                "access_token": "tok",
                "refresh_token": "ref",
                "project_id": "proj",
                "expires_at": None,
            }

            from app.adapters.gemini import GeminiAdapter

            adapter = GeminiAdapter()
            assert adapter._auth_mode == "oauth"
            assert adapter._cc_client is not None

            # Mock the CloudCodeClient's generate_content
            adapter._cc_client.generate_content = AsyncMock(return_value=response_data)

            result = await adapter.complete(
                [Message(role="user", content="Hi")],
                model="gemini-3-flash-preview",
            )
            assert result.content == "OAuth reply"
            adapter._cc_client.generate_content.assert_called_once()

    @pytest.mark.asyncio
    async def test_stream_routes_to_cloudcode(self):
        """When auth_mode=oauth, stream() uses cloudcode_stream."""
        chunks = [
            {"response": {"candidates": [{"content": {"role": "model", "parts": [{"text": "Hi"}]}}]}},
            {
                "response": {
                    "candidates": [{"content": {"role": "model", "parts": [{"text": "!"}]}, "finishReason": "STOP"}],
                    "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 2},
                },
            },
        ]

        async def mock_stream(*args: Any, **kwargs: Any):
            for chunk in chunks:
                yield chunk

        with (
            patch("app.adapters.gemini.resolve_oauth_data") as mock_oauth,
            patch("app.adapters.gemini.resolve_api_key", return_value=None),
            patch("app.adapters.gemini.get_gemini_auth_preference", return_value="oauth"),
        ):
            mock_oauth.return_value = {
                "access_token": "tok",
                "refresh_token": "ref",
                "project_id": "proj",
                "expires_at": None,
            }

            from app.adapters.gemini import GeminiAdapter

            adapter = GeminiAdapter()
            adapter._cc_client.stream_generate_content = mock_stream  # type: ignore[union-attr]

            events = []
            async for event in adapter.stream(
                [Message(role="user", content="Hi")],
                model="gemini-3-flash-preview",
            ):
                events.append(event)

            content_events = [e for e in events if e.type == "content"]
            assert len(content_events) == 2
            assert content_events[0].content == "Hi"


class TestCloudcodeStreamRetry:
    """Tests for streaming retry-before-content behavior."""

    @pytest.mark.asyncio
    async def test_retries_on_429_before_content(self):
        """429 before any content yields should retry transparently."""
        call_count = 0
        success_chunks = [
            {"response": {"candidates": [{"content": {"role": "model", "parts": [{"text": "OK"}]}}]}},
            {
                "response": {
                    "candidates": [{"content": {"role": "model", "parts": []}, "finishReason": "STOP"}],
                    "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 2},
                },
            },
        ]

        async def mock_stream(*args: Any, **kwargs: Any):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("HTTP 429 Resource exhausted")
            for chunk in success_chunks:
                yield chunk

        client = CloudCodeClient("tok", None, "proj")
        client.stream_generate_content = mock_stream  # type: ignore[assignment]

        events = []
        with patch("app.adapters._gemini_cloudcode_ops.asyncio.sleep", new=AsyncMock()):
            async for event in cloudcode_stream(
                client,
                [Message(role="user", content="Hi")],
                model="gemini-3-flash-preview",
            ):
                events.append(event)

        assert call_count == 2
        content_events = [e for e in events if e.type == "content"]
        assert len(content_events) == 1
        assert content_events[0].content == "OK"
        done_events = [e for e in events if e.type == "done"]
        assert len(done_events) == 1

    @pytest.mark.asyncio
    async def test_no_retry_after_content_yielded(self):
        """Error after content has been yielded should NOT retry."""
        async def mock_stream(*args: Any, **kwargs: Any):
            yield {"response": {"candidates": [{"content": {"role": "model", "parts": [{"text": "partial"}]}}]}}
            raise RuntimeError("HTTP 500 Internal Server Error")

        client = CloudCodeClient("tok", None, "proj")
        client.stream_generate_content = mock_stream  # type: ignore[assignment]

        events = []
        async for event in cloudcode_stream(
            client,
            [Message(role="user", content="Hi")],
            model="gemini-3-flash-preview",
        ):
            events.append(event)

        content_events = [e for e in events if e.type == "content"]
        assert len(content_events) == 1
        assert content_events[0].content == "partial"
        error_events = [e for e in events if e.type == "error"]
        assert len(error_events) == 1

    @pytest.mark.asyncio
    async def test_no_retry_on_non_retryable_error(self):
        """Non-retryable errors should emit error immediately."""
        async def mock_stream(*args: Any, **kwargs: Any):
            raise RuntimeError("Permission denied: invalid API key")
            yield  # make it an async generator

        client = CloudCodeClient("tok", None, "proj")
        client.stream_generate_content = mock_stream  # type: ignore[assignment]

        events = []
        async for event in cloudcode_stream(
            client,
            [Message(role="user", content="Hi")],
            model="gemini-3-flash-preview",
        ):
            events.append(event)

        error_events = [e for e in events if e.type == "error"]
        assert len(error_events) == 1
        assert "Permission denied" in error_events[0].error
