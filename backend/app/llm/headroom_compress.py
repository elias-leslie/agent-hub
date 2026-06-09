"""Flag-gated tool-result compression (Headroom transforms).

Compresses large ``ToolResultMessage`` text blocks before they re-enter the
model context, calling the ``headroom-ai`` Rust transforms **directly**:
:class:`SmartCrusher` for JSON arrays, :class:`LogCompressor` for logs / build
output.

Why call the transforms directly (not ``headroom.compress``)
============================================================
``headroom.compress`` is the full orchestrator and pulls the ``litellm``
provider router, which conflicts with this service's single-adapter mandate.
The transform classes need only the Rust engine (``headroom._core``) plus
``pydantic`` / ``tiktoken`` / ``opentelemetry-api`` — all of which are already
base dependencies. The ``compression`` optional group installs the engine with
``litellm`` (and ``ast-grep-cli``) excluded from resolution; see
``pyproject.toml`` ``[tool.uv] override-dependencies``. An import-guard test
asserts ``litellm`` never loads on this path.

Safety model — results stay self-contained and readable
=======================================================
* CCR (Compress-Cache-Retrieve) is **disabled** — ``CCRConfig(enabled=False)``
  for JSON, ``enable_ccr=False`` for logs. Compression therefore stays
  inline-readable: JSON arrays are losslessly tabularised (repeated keys
  factored into a schema header, every row kept), logs are summarised with the
  errors/traces preserved. No opaque ``<<ccr:HASH>>`` pointer is emitted — the
  agent has no ``headroom_retrieve`` tool, so a bare pointer would blind it to
  its own tool output. As belt-and-suspenders we still reject any output that
  contains ``<<ccr:``.
* Fail-safe — any import or compression error leaves the messages unchanged.
* Surgical — only ``ToolResultMessage`` ``TextContent`` is rewritten; message
  structure, tool-call ids, thinking blocks and signatures are untouched.
* Idempotent — already-compressed blocks are skipped, so per-turn cost is
  bounded by the newest, not-yet-compressed tool outputs.

Off by default. Enable with ``HEADROOM_COMPRESS_TOOL_RESULTS=1``.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.config import settings
from app.services.token_counter import count_tokens

from .types import Message, TextContent, ToolResultMessage

# Don't recompress already-compressed text. Matches the SmartCrusher tabular
# header (``[78]{schema}`` / ``"[78]{schema}``) and, defensively, the CCR
# retrieval marker (which CCR-disabled compression should never emit).
_COMPRESSED_RE = re.compile(r'^\s*"?\[\d+\]\{|Retrieve more: hash=')

# Below this, compression overhead exceeds savings (mirrors Headroom's own gate).
_MIN_CHARS = 2000
# Only accept a compressed block if it saves at least this fraction of tokens.
_MIN_GAIN = 0.10

def headroom_enabled() -> bool:
    """Master kill-switch — ``settings.headroom_compress_tool_results`` (off by default)."""
    return settings.headroom_compress_tool_results


def _allowlisted_slugs() -> frozenset[str]:
    """Per-agent opt-in allowlist parsed from the comma-separated setting."""
    return frozenset(
        slug.strip()
        for slug in settings.headroom_compress_agent_slugs.split(",")
        if slug.strip()
    )


def compression_enabled_for(agent_slug: str | None) -> bool:
    """Effective gate: master switch ON **and** ``agent_slug`` is allowlisted.

    Per-agent_slug opt-in (plan Phase 6) — JSON/log-heavy slugs are enabled via
    ``HEADROOM_COMPRESS_AGENT_SLUGS``; everything else stays off. The tool loop
    receives the resolved boolean, so the ``llm`` layer never reads settings.
    """
    if not agent_slug or not headroom_enabled():
        return False
    return agent_slug in _allowlisted_slugs()


def _looks_compressed(text: str) -> bool:
    return bool(_COMPRESSED_RE.search(text[:64]) or "Retrieve more: hash=" in text)


def _build_engines() -> tuple[Any, Any] | None:
    """Build (SmartCrusher, LogCompressor) with CCR disabled, or ``None`` when
    the engine isn't installed. Imports are local so the base install (no
    ``compression`` extra) fails safe instead of erroring at module import."""
    from headroom.config import CCRConfig
    from headroom.transforms.log_compressor import LogCompressor, LogCompressorConfig
    from headroom.transforms.smart_crusher import SmartCrusher

    crusher = SmartCrusher(ccr_config=CCRConfig(enabled=False))
    log_compressor = LogCompressor(LogCompressorConfig(enable_ccr=False))
    return crusher, log_compressor


def _accept(original: str, compressed: Any) -> tuple[str, int, int] | None:
    """Accept ``compressed`` only when it is SAFE and a real win.

    Returns ``(out, tokens_before, tokens_after)`` or ``None``. Safe means a
    non-empty string with no bare ``<<ccr:`` pointer; a real win means it saves
    at least :data:`_MIN_GAIN` of the original's tokens.
    """
    if not isinstance(compressed, str) or not compressed:
        return None
    if "<<ccr:" in compressed:  # opaque pointer — retrieval not wired, would blind the agent
        return None
    tokens_before = count_tokens(original)
    tokens_after = count_tokens(compressed)
    if tokens_after >= tokens_before * (1 - _MIN_GAIN):
        return None
    return compressed, tokens_before, tokens_after


def _compress_value(crusher: Any, log_compressor: Any, text: str) -> tuple[str, int, int] | None:
    """Route one string to the right inline compressor by content sniff.

    JSON array → SmartCrusher (tabularises rows). JSON object → envelope unwrap
    (compress its largest string value). Anything else → LogCompressor.
    """
    obj = _try_json(text)
    if isinstance(obj, list):
        return _accept(text, crusher.crush(text).compressed)
    if isinstance(obj, dict):
        return _unwrap_envelope(crusher, log_compressor, obj)
    # Not JSON — treat as log / build / search output.
    return _accept(text, log_compressor.compress(text).compressed)


def _unwrap_envelope(
    crusher: Any, log_compressor: Any, obj: dict[str, Any]
) -> tuple[str, int, int] | None:
    """Compress the largest string value of a JSON envelope inline.

    Many tools wrap their payload, e.g. ``{"output": "<28KB of logs>"}``. The
    wrapper itself doesn't compress, but routing the inner payload to the right
    per-type compressor does. Re-serialises the envelope with the inner value
    replaced; the gain/token counts are measured on the inner payload.
    """
    str_keys = [k for k, v in obj.items() if isinstance(v, str) and len(v) >= _MIN_CHARS]
    if not str_keys:
        return None
    key = max(str_keys, key=lambda k: len(obj[k]))
    inner = obj[key]
    inner_obj = _try_json(inner)
    if isinstance(inner_obj, list):
        compressed_inner = crusher.crush(inner).compressed
    else:
        compressed_inner = log_compressor.compress(inner).compressed
    accepted = _accept(inner, compressed_inner)
    if accepted is None:
        return None
    new_inner, tokens_before, tokens_after = accepted
    obj[key] = new_inner
    return json.dumps(obj), tokens_before, tokens_after


def _try_json(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:
        return None


def compress_tool_results(
    messages: list[Message],
    model_id: str,
) -> tuple[list[Message], dict[str, Any]]:
    """Compress large tool-result text blocks in place.

    Returns ``(messages, stats)``. ``messages`` is the same list (mutated in
    place); ``stats`` reports blocks touched and tokens saved for observability.
    Never raises — on any failure the originals pass through unchanged.

    ``model_id`` is accepted for call-site symmetry with the loop; the inline
    transforms are model-agnostic, so it is not currently consulted.
    """
    stats: dict[str, Any] = {
        "blocks_seen": 0,
        "blocks_compressed": 0,
        "tokens_before": 0,
        "tokens_after": 0,
    }

    try:
        engines = _build_engines()
    except Exception:
        stats["error"] = "headroom-ai engine not available"
        return messages, stats
    if engines is None:
        stats["error"] = "headroom-ai engine not available"
        return messages, stats
    crusher, log_compressor = engines

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
                result = _compress_value(crusher, log_compressor, text)
            except Exception:
                # Fail-safe: leave this block untouched, keep going.
                continue
            if result is None:
                continue
            out, tokens_before, tokens_after = result
            block.text = out
            stats["blocks_compressed"] += 1
            stats["tokens_before"] += tokens_before
            stats["tokens_after"] += tokens_after

    return messages, stats


__all__ = ["compress_tool_results", "compression_enabled_for", "headroom_enabled"]
