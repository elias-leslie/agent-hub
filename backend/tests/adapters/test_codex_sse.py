"""Tests for Codex SSE helpers."""

from __future__ import annotations

import json

import pytest

from app.adapters.codex_sse import build_request_body, collect_completion


class TestBuildRequestBody:
    def test_includes_reasoning_and_verbosity(self) -> None:
        body = build_request_body(
            [{"role": "user", "content": [{"type": "input_text", "text": "Hi"}]}],
            "codex/gpt-5.4",
            reasoning_effort="xhigh",
            verbosity_level="high",
            max_tokens=512,
        )

        assert body["reasoning"] == {"effort": "xhigh", "summary": "auto"}
        assert body["text"] == {"verbosity": "high"}
        assert body["max_output_tokens"] == 512

    def test_includes_tool_and_cache_fields_when_requested(self) -> None:
        body = build_request_body(
            [{"role": "user", "content": [{"type": "input_text", "text": "Hi"}]}],
            "codex/gpt-5.4",
            tools=[{
                "type": "function",
                "name": "read_file",
                "description": "Read a file",
                "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
            }],
            prompt_cache_key="sess-123",
        )

        assert body["tools"] == [
            {
                "type": "function",
                "name": "read_file",
                "description": "Read a file",
                "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
            },
        ]
        assert body["tool_choice"] == "auto"
        assert body["parallel_tool_calls"] is True
        assert body["prompt_cache_key"] == "sess-123"


class _FakeSSELineResponse:
    def __init__(self, events: list[dict[str, object]]) -> None:
        self._lines = [f"data: {json.dumps(event)}" for event in events]
        self._lines.append("data: [DONE]")

    async def aiter_lines(self):  # pragma: no cover - exercised via collect_completion
        for line in self._lines:
            yield line


class TestCollectCompletion:
    @pytest.mark.asyncio
    async def test_collects_tool_calls_and_reasoning(self) -> None:
        response = _FakeSSELineResponse([
            {
                "type": "response.output_item.added",
                "item": {
                    "type": "reasoning",
                    "id": "rs_1",
                    "summary": [{"type": "summary_text", "text": ""}],
                },
            },
            {"type": "response.reasoning_summary_text.delta", "delta": "Plan first."},
            {
                "type": "response.output_item.added",
                "item": {
                    "type": "function_call",
                    "id": "fc_1",
                    "call_id": "call_1",
                    "name": "read_file",
                    "arguments": "",
                },
            },
            {
                "type": "response.output_item.done",
                "item": {
                    "type": "reasoning",
                    "id": "rs_1",
                },
            },
            {"type": "response.function_call_arguments.delta", "delta": "{\"path\":\"README.md\"}"},
            {
                "type": "response.output_item.done",
                "item": {
                    "type": "function_call",
                    "id": "fc_1",
                    "call_id": "call_1",
                    "name": "read_file",
                    "arguments": "{\"path\":\"README.md\"}",
                },
            },
            {
                "type": "response.completed",
                "response": {
                    "status": "completed",
                    "model": "codex/gpt-5.4",
                    "usage": {"input_tokens": 11, "output_tokens": 7},
                },
            },
        ])

        result = await collect_completion(response, "codex/gpt-5.4")

        assert result.thinking_content == "Plan first."
        assert result.tool_calls is not None
        assert result.tool_calls[0].id == "call_1"
        assert result.tool_calls[0].name == "read_file"
        assert result.tool_calls[0].input == {"path": "README.md"}
        assert result.finish_reason == "stop"
