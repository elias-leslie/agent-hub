"""Pi's native JSONL records, translated into the existing event contract."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

from app.services.session_ingestion.models import NormalizedEvent, SessionUpsertRequest

from ._event_builders import _ParseState
from .base import ProviderBoundary, ProviderSessionRef

PI_RECORD_TYPES = frozenset({
    "session", "message", "model_change", "thinking_level_change", "usage",
    "compaction", "branch_summary", "custom", "label", "session_info",
    "custom_message", "context_edit",
})


class PiTranscriptAdapter:
    """Reuse the incremental JSONL reader and canonical lifecycle boundary."""

    provider_name = "pi"

    async def discover_sessions(self) -> list[ProviderSessionRef]:
        return []

    async def build_session_metadata(self, session_ref: ProviderSessionRef) -> SessionUpsertRequest:
        return SessionUpsertRequest(
            session_id=session_ref.provider_session_id, project_id="unknown", provider="pi",
            model="unknown", session_type="pi",
            provider_metadata={"transcript_path": session_ref.source_id} if session_ref.source_id else {},
        )

    async def read_new_events(self, session_ref: ProviderSessionRef, checkpoint: str | None = None
                              ) -> tuple[list[NormalizedEvent], str | None]:
        from .transcript_parsers import read_incremental_transcript_events

        if not session_ref.source_id:
            return [], checkpoint
        _, header = await asyncio.to_thread(pi_header, session_ref.source_id, session_ref.provider_session_id)
        events, next_checkpoint = await asyncio.to_thread(read_incremental_transcript_events, session_ref.source_id, checkpoint)
        # Native forks copy their ancestors' entries unchanged. They remain
        # history, but are not fresh calls charged to the new session.
        parent = header.get("parentSession")
        if events and isinstance(parent, str):
            inherited = await asyncio.to_thread(inherited_sources, parent)
            events = [event for event in events
                      if not event.source_event_id or event.source_event_id.rsplit(":", 1)[0] not in inherited]
        return events, next_checkpoint

    async def detect_boundaries(self, session_ref: ProviderSessionRef, checkpoint: str | None = None
                                ) -> list[ProviderBoundary]:
        return [ProviderBoundary(boundary_type="opened")] if checkpoint is None else []


def pi_header(transcript: str, session_id: str) -> tuple[Path, dict]:
    from .transcript_parsers import contained_transcript_path

    path = contained_transcript_path(transcript)
    if path is None or path.suffix != ".jsonl":
        raise ValueError("Pi transcript must be inside the configured native transcript roots")
    with path.open("rb") as source:
        raw = source.readline(64 * 1024)
    header = json.loads(raw)
    if (not raw.endswith(b"\n") or not isinstance(header, dict) or header.get("type") != "session"
            or header.get("id") != session_id
            or not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", session_id)):
        raise ValueError("Pi transcript identity does not match the native session")
    return path, header


def inherited_sources(transcript: str) -> set[str]:
    from .transcript_parsers import contained_transcript_path

    path = contained_transcript_path(transcript)
    if path is None or path.suffix != ".jsonl":
        raise ValueError("Pi parent transcript is outside the configured native roots")
    identities: set[str] = set()
    with path.open("rb") as source:
        for raw in source:
            if not raw.endswith(b"\n"):
                break
            row = json.loads(raw)
            if isinstance(row, dict) and isinstance(row.get("id"), str):
                identities.add(f"{row.get('type')}:{row['id']}")
    return identities


def _text(content: object) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    texts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text")
            if isinstance(text, str):
                texts.append(text)
    return "\n".join(texts)


def _count(usage: dict[str, Any], name: str) -> int | None:
    value = usage.get(name)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def append_pi_events(obj: dict[str, Any], state: _ParseState) -> None:
    kind = obj.get("type")
    entry_id = obj.get("id")
    if not isinstance(entry_id, str) or not entry_id:
        return
    # Pi IDs survive replay and append-only branch changes. Keep the record's
    # own identity rather than a path/inode alias as its event source.
    state.set_source(obj, entry_id)
    message = obj.get("message") if kind == "message" else None
    message = message if isinstance(message, dict) else {}
    role = message.get("role")
    provider, model = message.get("provider"), message.get("model")
    model_used = f"{provider}/{model}" if isinstance(provider, str) and isinstance(model, str) else None
    if role == "user":
        state.begin_user_turn()
        state.append("user_message", role="user", content=_text(message.get("content")))
    elif role == "assistant":
        content = message.get("content")
        for block in content if isinstance(content, list) else []:
            if not isinstance(block, dict):
                continue
            if block.get("type") in {"text", "thinking"}:
                thinking = block["type"] == "thinking"
                text = block.get("thinking" if thinking else "text")
                if isinstance(text, str) and text:
                    state.append("thinking" if thinking else "assistant_message",
                                 role="assistant", content=text, model_used=model_used)
            elif block.get("type") == "toolCall":
                state.append("tool_use", role="assistant", tool_name=block.get("name"),
                             call_id=block.get("id"), tool_input=block.get("arguments"),
                             model_used=model_used)
        if message.get("errorMessage"):
            state.append("error", content=str(message["errorMessage"]), model_used=model_used)
    elif role == "toolResult":
        state.append("tool_result", role="tool", call_id=message.get("toolCallId"),
                     tool_name=message.get("toolName"),
                     tool_output={"text": _text(message.get("content")), "isError": message.get("isError", False)})
    elif kind in {"compaction", "branch_summary"}:
        state.append("system", content=obj.get("summary"))

    usage = message.get("usage") if role in {"assistant", "toolResult"} else obj.get("usage")
    if not isinstance(usage, dict):
        return
    native_input, cached, written = (_count(usage, key) for key in ("input", "cacheRead", "cacheWrite"))
    output = _count(usage, "output")
    counts = [native_input, cached, written]
    # Pi input excludes cache read/write; Agent Hub's response input includes both.
    normalized = {
        "scope": "response", "source": "pi.transcript", "response_id": entry_id,
        "input_tokens": sum(value or 0 for value in counts) if any(value is not None for value in counts) else None,
        "output_tokens": output, "cached_input_tokens": cached,
        "cache_write_tokens": written, "native": usage,
    }
    if kind == "usage":
        model_used = f"{obj.get('provider')}/{obj.get('model')}"
    state.append("usage", model_used=model_used, usage=normalized)
