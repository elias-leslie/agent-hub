"""Hermetic tests for Headroom tool-result compression (app.llm.headroom_compress).

Covers the production transforms path: JSON arrays tabularise (data-lossless),
log blobs summarise (errors preserved), the ``{"output": ...}`` envelope is
unwrapped, compression is idempotent, ``<<ccr:>`` pointers are rejected, the hook
fails safe when the engine is absent, and — the load-bearing guarantee — using
the compressor never imports ``litellm``.

These run against the real ``headroom-ai`` engine (installed via the
``compression`` optional group); no ``/tmp`` fixtures, no network.
"""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest

import app.llm.headroom_compress as hc
from app.llm.headroom_compress import (
    compress_tool_results,
    compression_enabled_for,
)
from app.llm.types import Message, TextContent, ToolResultMessage


def _tool_result(text: str) -> ToolResultMessage:
    return ToolResultMessage(
        tool_call_id="tc-1",
        tool_name="some_tool",
        content=[TextContent(text=text)],
        is_error=False,
        timestamp=0,
    )


def _text(msg: Message) -> str:
    """First content block's text (tool results always carry a TextContent)."""
    block = msg.content[0]
    assert isinstance(block, TextContent)
    return block.text


def _json_array(n: int = 100) -> str:
    return json.dumps(
        [
            {"id": i, "name": f"user_{i}", "email": f"user_{i}@example.com", "role": "member"}
            for i in range(n)
        ]
    )


def _log_blob(n: int = 200) -> str:
    lines = [f"2026-06-08 12:00:{i % 60:02d} INFO worker batch {i} ok latency=12ms" for i in range(n)]
    lines.append("2026-06-08 12:05:00 ERROR boom: unique-traceback-marker")
    return "\n".join(lines)


# --- core transforms -------------------------------------------------------


def test_json_array_compresses_and_preserves_every_row():
    payload = _json_array(100)
    msg = _tool_result(payload)

    out, stats = compress_tool_results([msg], "claude-opus-4-8")

    compressed = _text(out[0])
    assert len(compressed) < len(payload)
    assert stats["blocks_compressed"] == 1
    assert stats["tokens_after"] < stats["tokens_before"]
    # Data-lossless: first, last, and a middle row's values all survive.
    for i in (0, 50, 99):
        assert f"user_{i}@example.com" in compressed
        assert f"user_{i}" in compressed


def test_log_blob_compresses_and_keeps_errors():
    blob = _log_blob(200)
    msg = _tool_result(blob)

    out, stats = compress_tool_results([msg], "m")

    compressed = _text(out[0])
    assert stats["blocks_compressed"] == 1
    assert len(compressed) < len(blob)
    assert "unique-traceback-marker" in compressed


def test_envelope_payload_is_unwrapped_and_recompressed():
    inner = _json_array(100)
    envelope = json.dumps({"output": inner})
    msg = _tool_result(envelope)

    out, stats = compress_tool_results([msg], "m")

    compressed = _text(out[0])
    assert stats["blocks_compressed"] == 1
    # Still a valid envelope; the wrapper key survives, the inner payload shrank.
    outer = json.loads(compressed)
    assert "output" in outer
    assert len(outer["output"]) < len(inner)


def test_compression_is_idempotent():
    msg = _tool_result(_json_array(100))

    once, _ = compress_tool_results([msg], "m")
    twice, stats2 = compress_tool_results(once, "m")

    # Second pass recognises the tabular header and touches nothing.
    assert stats2["blocks_compressed"] == 0
    assert _text(twice[0]) == _text(once[0])


def test_small_payload_is_skipped():
    msg = _tool_result(json.dumps([{"id": 1}]))  # well under _MIN_CHARS

    out, stats = compress_tool_results([msg], "m")

    assert stats["blocks_seen"] == 0
    assert stats["blocks_compressed"] == 0
    assert _text(out[0]) == json.dumps([{"id": 1}])


# --- safety: CCR rejection + fail-safe -------------------------------------


class _FakeResult:
    def __init__(self, compressed: str) -> None:
        self.compressed = compressed


class _FakeEngine:
    """Stand-in crusher/log-compressor returning a fixed payload."""

    def __init__(self, out: str) -> None:
        self._out = out

    def crush(self, _text: str) -> _FakeResult:
        return _FakeResult(self._out)

    def compress(self, _text: str) -> _FakeResult:
        return _FakeResult(self._out)


def test_ccr_pointer_output_is_rejected(monkeypatch):
    # If the engine ever emitted an opaque CCR pointer, _accept must refuse it
    # (the agent has no retrieve tool — a bare pointer would blind it).
    poisoned = '"[1]{a:int}\n<<ccr:deadbeef>>'
    monkeypatch.setattr(hc, "_build_engines", lambda: (_FakeEngine(poisoned), _FakeEngine(poisoned)))
    original = _json_array(100)
    msg = _tool_result(original)

    out, stats = compress_tool_results([msg], "m")

    assert stats["blocks_compressed"] == 0
    assert _text(out[0]) == original  # untouched


def test_failsafe_when_engine_absent(monkeypatch):
    def _boom() -> None:
        raise ImportError("headroom-ai not installed")

    monkeypatch.setattr(hc, "_build_engines", _boom)
    original = _json_array(100)
    msg = _tool_result(original)

    out, stats = compress_tool_results([msg], "m")

    assert _text(out[0]) == original
    assert "error" in stats


def test_non_tool_result_messages_untouched():
    # Guard: only ToolResultMessage blocks are ever rewritten.
    from app.llm.types import UserMessage

    user = UserMessage(content=_json_array(100), timestamp=0)
    out, stats = compress_tool_results([user], "m")

    assert stats["blocks_seen"] == 0
    assert out[0] is user


# --- the load-bearing guarantee: no litellm --------------------------------


def test_using_compressor_never_imports_litellm():
    # The whole transforms-only design exists to keep litellm out of the
    # process (single-adapter mandate). Exercise the real engine, then assert.
    msg = _tool_result(_json_array(100))
    compress_tool_results([msg], "claude-opus-4-8")

    assert "litellm" not in sys.modules


# --- Phase 2 gating --------------------------------------------------------


@pytest.mark.parametrize(
    ("master", "allowlist", "slug", "expected"),
    [
        (True, "agent-a,agent-b", "agent-a", True),
        (True, "agent-a,agent-b", "agent-c", False),
        (False, "agent-a", "agent-a", False),  # master kill-switch wins
        (True, "", "agent-a", False),  # empty allowlist → nobody
        (True, "agent-a", None, False),  # no slug → off
    ],
)
def test_compression_enabled_for(monkeypatch, master, allowlist, slug, expected):
    monkeypatch.setattr(
        hc,
        "settings",
        SimpleNamespace(
            headroom_compress_tool_results=master,
            headroom_compress_agent_slugs=allowlist,
        ),
    )
    assert compression_enabled_for(slug) is expected
