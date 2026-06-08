"""Flag-gated tool-result compression (Headroom) — PROTOTYPE.

Compresses large ``ToolResultMessage`` text blocks before they re-enter the
model context, using the ``headroom-ai`` pipeline (SmartCrusher for JSON,
LogCompressor for logs/search output).

SAFETY MODEL — the result must stay self-contained and readable
================================================================
Headroom has two outcomes:

* **Inline-readable** — JSON is losslessly tabularised (repeated keys factored
  into a schema header, every row kept) or logs are summarised with an inline
  ``Retrieve more: hash=...`` hint. The model can still read everything it
  needs directly. SAFE.
* **Opaque CCR pointer** — large opaque blobs are replaced wholesale with a
  ``<<ccr:HASH,kind,size>>`` marker; the bytes live in Headroom's CCR store
  and come back only via a ``headroom_retrieve`` tool. We have NOT wired that
  tool into the agent tool-set, so a bare pointer would blind the agent to its
  own tool output. UNSAFE — rejected here (the original is kept).

Real-data testing (a 262-tool-output Codex session) showed the naive path
turned 237/262 outputs into bare pointers (95% "savings" that hide the data);
rejecting pointers + unwrapping JSON envelopes yields ~29% fully-readable
savings on that code-heavy session, and 67-95% on JSON/log-heavy outputs.

Off by default. Enable with ``HEADROOM_COMPRESS_TOOL_RESULTS=1``.

Design constraints honoured:
* Single surface — the one async tool loop (``tool_loop.run``) calls
  :func:`compress_tool_results` in a thread executor; nothing else changes.
* Fail-safe — any import/compression error keeps the messages unchanged.
* Surgical — only ``ToolResultMessage`` ``TextContent`` is touched; message
  structure, tool-call ids, thinking blocks and signatures are untouched.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from typing import Any

from .types import Message, TextContent, ToolResultMessage

# Don't recompress already-compressed text. Matches the SmartCrusher tabular
# header (``[78]{schema}`` / ``"[78]{schema}``) and the CCR retrieval marker.
_COMPRESSED_RE = re.compile(r'^\s*"?\[\d+\]\{|Retrieve more: hash=')

# Below this, compression overhead exceeds savings (mirrors Headroom's own gate).
_MIN_CHARS = 2000
# Only accept a compressed block if it saves at least this fraction.
_MIN_GAIN = 0.10

_ENV_FLAG = "HEADROOM_COMPRESS_TOOL_RESULTS"


def headroom_enabled() -> bool:
    """True when the prototype flag is set (off by default)."""
    return os.environ.get(_ENV_FLAG, "").strip().lower() in {"1", "true", "yes", "on"}


def _looks_compressed(text: str) -> bool:
    return bool(_COMPRESSED_RE.search(text[:64]) or "Retrieve more: hash=" in text)


def _compress_once(
    hr_compress: Callable[..., Any], text: str, model_id: str
) -> tuple[str, int, int] | None:
    """Compress one string. Return ``(out, tokens_before, tokens_after)`` only
    when the result is SAFE — self-contained (no bare ``<<ccr:`` pointer) and a
    real win. Otherwise ``None``."""
    res = hr_compress([{"role": "tool", "content": text}], model=model_id, protect_recent=0)
    out = res.messages[0].get("content")
    if not isinstance(out, str) or not out:
        return None
    if "<<ccr:" in out:  # opaque pointer — retrieval not wired, would blind the agent
        return None
    if res.tokens_after >= res.tokens_before * (1 - _MIN_GAIN):
        return None
    return out, res.tokens_before, res.tokens_after


def _safe_compress(
    hr_compress: Callable[..., Any], text: str, model_id: str
) -> tuple[str, int, int] | None:
    """Best safe compression of ``text``. Tries the raw form, then — if the raw
    form is an opaque JSON envelope (e.g. ``{"output": "<28KB of logs>"}``) —
    compresses its largest string value inline so the right per-type compressor
    fires instead of a wholesale pointer offload."""
    direct = _compress_once(hr_compress, text, model_id)
    if direct is not None:
        return direct
    # JSON-envelope unwrap: route the inner payload to the inline compressors.
    try:
        obj = json.loads(text)
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    str_keys = [k for k, v in obj.items() if isinstance(v, str) and len(v) >= _MIN_CHARS]
    if not str_keys:
        return None
    key = max(str_keys, key=lambda k: len(obj[k]))
    inner = _compress_once(hr_compress, obj[key], model_id)
    if inner is None:
        return None
    new_inner, tb, ta = inner
    obj[key] = new_inner
    return json.dumps(obj), tb, ta


def compress_tool_results(
    messages: list[Message],
    model_id: str,
) -> tuple[list[Message], dict[str, Any]]:
    """Compress large tool-result text blocks in place.

    Returns ``(messages, stats)``. ``messages`` is the same list (mutated in
    place); ``stats`` reports blocks touched and tokens saved for observability.
    Never raises — on any failure the originals pass through unchanged.
    """
    stats: dict[str, Any] = {
        "blocks_seen": 0,
        "blocks_compressed": 0,
        "tokens_before": 0,
        "tokens_after": 0,
    }

    try:
        from headroom import compress as _hr_compress
    except Exception:
        stats["error"] = "headroom-ai not installed"
        return messages, stats

    for msg in messages:
        if not isinstance(msg, ToolResultMessage):
            continue
        for block in msg.content:
            if not isinstance(block, TextContent):
                continue
            text = block.text
            if len(text) < _MIN_CHARS or _looks_compressed(text):
                continue
            stats["blocks_seen"] += 1
            try:
                safe = _safe_compress(_hr_compress, text, model_id)
            except Exception:
                # Fail-safe: leave this block untouched, keep going.
                continue
            if safe is None:
                continue
            out, tb, ta = safe
            block.text = out
            stats["blocks_compressed"] += 1
            stats["tokens_before"] += tb
            stats["tokens_after"] += ta

    return messages, stats


__all__ = ["compress_tool_results", "headroom_enabled"]
