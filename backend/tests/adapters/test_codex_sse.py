"""Tests for Codex SSE helpers."""

from app.adapters.codex_sse import build_request_body


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
