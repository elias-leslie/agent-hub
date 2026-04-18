"""Tests for streaming functionality."""

import json

import httpx
import pytest
from pytest_httpx import HTTPXMock

from agent_hub import AsyncAgentHubClient, StreamChunk


class TestStreamSSE:
    """Tests for SSE streaming."""

    @pytest.mark.asyncio
    async def test_stream_sse_success(self, httpx_mock: HTTPXMock) -> None:
        """Test successful SSE streaming."""
        # SSE response body in native Agent Hub format
        sse_body = (
            'data: {"type":"content","content":"Hello"}\n\n'
            'data: {"type":"content","content":" world"}\n\n'
            'data: {"type":"done","finish_reason":"end_turn","input_tokens":10,"output_tokens":5}\n\n'
        )

        httpx_mock.add_response(
            url="http://localhost:8003/api/complete",
            method="POST",
            content=sse_body.encode(),
            headers={"content-type": "text/event-stream"},
        )

        async with AsyncAgentHubClient() as client:
            chunks = []
            async for chunk in client.stream_sse(
                model="claude-sonnet-4-6",
                messages=[{"role": "user", "content": "Hello"}],
                project_id="test-project",
            ):
                chunks.append(chunk)

        # Should have: 2 content chunks + 1 done
        assert len(chunks) == 3
        assert chunks[0].type == "content"
        assert chunks[0].content == "Hello"
        assert chunks[1].type == "content"
        assert chunks[1].content == " world"
        assert chunks[2].type == "done"
        assert chunks[2].finish_reason == "end_turn"

    @pytest.mark.asyncio
    async def test_stream_sse_with_message_input(self, httpx_mock: HTTPXMock) -> None:
        """Test SSE streaming with MessageInput objects."""
        from agent_hub import MessageInput

        sse_body = (
            'data: {"type":"content","content":"Response"}\n\n'
            'data: {"type":"done","finish_reason":"end_turn"}\n\n'
        )

        httpx_mock.add_response(
            url="http://localhost:8003/api/complete",
            method="POST",
            content=sse_body.encode(),
            headers={"content-type": "text/event-stream"},
        )

        async with AsyncAgentHubClient() as client:
            chunks = []
            async for chunk in client.stream_sse(
                model="claude-sonnet-4-6",
                messages=[MessageInput(role="user", content="Hello")],
                project_id="test-project",
            ):
                chunks.append(chunk)

        assert len(chunks) == 2
        assert chunks[0].content == "Response"

    @pytest.mark.asyncio
    async def test_stream_sse_done_marker(self, httpx_mock: HTTPXMock) -> None:
        """Test SSE streaming handles [DONE] marker."""
        sse_body = 'data: {"type":"content","content":"Text"}\n\ndata: [DONE]\n\n'

        httpx_mock.add_response(
            url="http://localhost:8003/api/complete",
            method="POST",
            content=sse_body.encode(),
            headers={"content-type": "text/event-stream"},
        )

        async with AsyncAgentHubClient() as client:
            chunks = []
            async for chunk in client.stream_sse(
                model="claude-sonnet-4-6",
                messages=[{"role": "user", "content": "Hello"}],
                project_id="test-project",
            ):
                chunks.append(chunk)

        # Should have just the content chunk - [DONE] stops iteration
        assert len(chunks) == 1
        assert chunks[0].type == "content"
        assert chunks[0].content == "Text"

    @pytest.mark.asyncio
    async def test_stream_sse_supports_agentic_payload_and_tool_events(
        self,
        httpx_mock: HTTPXMock,
    ) -> None:
        sse_body = (
            'data: {"type":"thinking","content":"considering"}\n\n'
            'data: {"type":"tool_use","tool_id":"tool-1","tool_name":"bash","tool_input":{"command":"git rev-parse --abbrev-ref HEAD"}}\n\n'
            'data: {"type":"tool_result","tool_id":"tool-1","tool_result":"main","tool_status":"complete"}\n\n'
            'data: {"type":"done","finish_reason":"stop","session_id":"sess-1"}\n\n'
        )
        captured_payload: dict[str, object] = {}
        captured_headers: dict[str, str] = {}

        def handler(request):
            nonlocal captured_payload, captured_headers
            captured_payload = json.loads(request.content.decode())
            captured_headers = dict(request.headers)
            return httpx.Response(
                status_code=200,
                content=sse_body.encode(),
                headers={"content-type": "text/event-stream"},
            )

        httpx_mock.add_callback(
            handler,
            url="http://localhost:8003/api/complete",
            method="POST",
        )

        async with AsyncAgentHubClient() as client:
            chunks = []
            async for chunk in client.stream_sse(
                agent_slug="coder",
                messages=[{"role": "user", "content": "Check branch"}],
                project_id="test-project",
                execute_tools=True,
                max_turns=2,
                working_dir="/tmp/checkout",
                skip_cache=True,
            ):
                chunks.append(chunk)

        assert captured_payload["stream"] is True
        assert captured_payload["execute_tools"] is True
        assert captured_payload["max_turns"] == 2
        assert captured_payload["working_dir"] == "/tmp/checkout"
        assert captured_headers["x-skip-cache"] == "true"
        assert [chunk.type for chunk in chunks] == ["thinking", "tool_use", "tool_result", "done"]
        assert chunks[1].tool_call is not None
        assert chunks[1].tool_call.name == "bash"
        assert chunks[2].tool_result == "main"
        assert chunks[2].tool_status == "complete"


class TestStreamChunkModel:
    """Tests for StreamChunk model."""

    def test_stream_chunk_content(self) -> None:
        """Test content chunk creation."""
        chunk = StreamChunk(type="content", content="Hello world")
        assert chunk.type == "content"
        assert chunk.content == "Hello world"
        assert chunk.error is None

    def test_stream_chunk_done(self) -> None:
        """Test done chunk with token counts."""
        chunk = StreamChunk(
            type="done",
            input_tokens=100,
            output_tokens=50,
            finish_reason="end_turn",
        )
        assert chunk.type == "done"
        assert chunk.input_tokens == 100
        assert chunk.output_tokens == 50
        assert chunk.finish_reason == "end_turn"

    def test_stream_chunk_error(self) -> None:
        """Test error chunk."""
        chunk = StreamChunk(type="error", error="Connection failed")
        assert chunk.type == "error"
        assert chunk.error == "Connection failed"

    def test_stream_chunk_cancelled(self) -> None:
        """Test cancelled chunk."""
        chunk = StreamChunk(
            type="cancelled",
            input_tokens=50,
            output_tokens=25,
            finish_reason="cancelled",
        )
        assert chunk.type == "cancelled"
        assert chunk.finish_reason == "cancelled"

    def test_stream_chunk_tool_result(self) -> None:
        """Test tool result chunk."""
        chunk = StreamChunk(
            type="tool_result",
            tool_id="tool-1",
            tool_result="main",
            tool_status="complete",
        )
        assert chunk.type == "tool_result"
        assert chunk.tool_id == "tool-1"
        assert chunk.tool_result == "main"
        assert chunk.tool_status == "complete"
