"""Shared transcript-to-normalized-event parsers for external providers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.session_ingestion.models import NormalizedEvent

JsonObject = dict[str, object]


def read_jsonl_lines(transcript_path: str, checkpoint: str | None = None) -> tuple[list[str], str | None]:
    """Read JSONL transcript lines from an optional line-offset checkpoint."""
    path = Path(transcript_path)
    if not path.exists() or path.suffix != ".jsonl":
        return [], checkpoint

    try:
        lines = path.read_text().splitlines()
    except OSError:
        return [], checkpoint

    start = int(checkpoint) if checkpoint and checkpoint.isdigit() else 0
    return lines[start:], str(len(lines))


def parse_transcript_events(lines: list[str]) -> list[NormalizedEvent]:
    """Parse supported transcript JSONL entries into normalized events."""
    state = _ParseState()
    _parse_transcript_lines(lines, state)
    return state.events


def read_incremental_transcript_events(
    transcript_path: str,
    checkpoint: str | None = None,
) -> tuple[list[NormalizedEvent], str | None]:
    """Read and parse transcript deltas while preserving parser state across checkpoints."""
    path = Path(transcript_path)
    if not path.exists() or path.suffix != ".jsonl":
        return [], checkpoint

    try:
        lines = path.read_text().splitlines()
    except OSError:
        return [], checkpoint

    parser_checkpoint = _load_parse_checkpoint(checkpoint, line_count=len(lines))
    state = _ParseState.from_checkpoint(parser_checkpoint)
    _parse_transcript_lines(lines[parser_checkpoint.line_offset :], state)
    return state.events, _dump_parse_checkpoint(line_count=len(lines), state=state)


def _parse_transcript_lines(lines: list[str], state: _ParseState) -> None:
    """Parse transcript lines into the provided mutable state."""
    for raw_line in lines:
        obj = _parse_jsonl_line(raw_line)
        if obj is None:
            continue
        _append_normalized_events(obj, state)


def _parse_jsonl_line(raw_line: str) -> JsonObject | None:
    try:
        parsed = json.loads(raw_line)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


@dataclass(slots=True)
class _TranscriptParseCheckpoint:
    """Opaque checkpoint for incremental transcript parsing."""

    line_offset: int = 0
    turn: int = 1
    sequence: int = 0
    saw_content: bool = False


class _ParseState:
    """Mutable transcript parsing state."""

    def __init__(self, *, turn: int = 1, sequence: int = 0, saw_content: bool = False) -> None:
        self.turn = turn
        self.sequence = sequence
        self.events: list[NormalizedEvent] = []
        self._saw_content = saw_content

    @classmethod
    def from_checkpoint(cls, checkpoint: _TranscriptParseCheckpoint) -> _ParseState:
        return cls(
            turn=checkpoint.turn,
            sequence=checkpoint.sequence,
            saw_content=checkpoint.saw_content,
        )

    def begin_user_turn(self) -> None:
        if self._saw_content:
            self.turn += 1
        self.sequence = 0

    def append(self, event_type: str, **kwargs: Any) -> None:
        self.sequence += 1
        self._saw_content = True
        self.events.append(
            NormalizedEvent(
                event_type=event_type,
                turn=self.turn,
                sequence=self.sequence,
                **kwargs,
            )
        )


def _load_parse_checkpoint(
    checkpoint: str | None,
    *,
    line_count: int,
) -> _TranscriptParseCheckpoint:
    """Load an opaque parser checkpoint, reparsing from start for legacy or invalid values."""
    if not checkpoint or checkpoint.isdigit():
        return _TranscriptParseCheckpoint()
    try:
        parsed = json.loads(checkpoint)
    except json.JSONDecodeError:
        return _TranscriptParseCheckpoint()
    if not isinstance(parsed, dict):
        return _TranscriptParseCheckpoint()
    line_offset = parsed.get("line_offset")
    turn = parsed.get("turn")
    sequence = parsed.get("sequence")
    saw_content = parsed.get("saw_content")
    if not isinstance(line_offset, int) or line_offset < 0 or line_offset > line_count:
        return _TranscriptParseCheckpoint()
    if not isinstance(turn, int) or turn < 1:
        return _TranscriptParseCheckpoint()
    if not isinstance(sequence, int) or sequence < 0:
        return _TranscriptParseCheckpoint()
    if not isinstance(saw_content, bool):
        return _TranscriptParseCheckpoint()
    return _TranscriptParseCheckpoint(
        line_offset=line_offset,
        turn=turn,
        sequence=sequence,
        saw_content=saw_content,
    )


def _dump_parse_checkpoint(*, line_count: int, state: _ParseState) -> str:
    """Serialize the parser state into the opaque checkpoint string."""
    return json.dumps(
        {
            "line_offset": line_count,
            "turn": state.turn,
            "sequence": state.sequence,
            "saw_content": state._saw_content,
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def _append_normalized_events(obj: JsonObject, state: _ParseState) -> None:
    entry_type = obj.get("type")
    if entry_type == "progress":
        _append_claude_progress_events(obj, state)
        return
    if entry_type == "user" and not obj.get("isMeta"):
        _append_claude_user_events(obj, state)
        return
    if entry_type == "assistant":
        _append_claude_assistant_events(obj, state)
        return
    if entry_type == "response_item":
        _append_codex_response_item(obj.get("payload"), state)


def _append_claude_user_events(obj: JsonObject, state: _ParseState) -> None:
    message = obj.get("message")
    if not isinstance(message, dict):
        return
    _append_claude_user_message(message, state)


def _append_claude_assistant_events(obj: JsonObject, state: _ParseState) -> None:
    message = obj.get("message")
    if not isinstance(message, dict):
        return
    _append_claude_assistant_message(message, state)


def _append_claude_progress_events(obj: JsonObject, state: _ParseState) -> None:
    data = obj.get("data")
    if not isinstance(data, dict) or data.get("type") != "agent_progress":
        return
    nested = data.get("message")
    if not isinstance(nested, dict):
        return
    nested_type = nested.get("type")
    message = nested.get("message")
    if not isinstance(message, dict):
        return
    agent_id = data.get("agentId") if isinstance(data.get("agentId"), str) else None
    agent_name = obj.get("slug") if isinstance(obj.get("slug"), str) else None
    if nested_type == "assistant":
        _append_claude_assistant_message(
            message,
            state,
            agent_id=agent_id,
            agent_name=agent_name,
        )
    elif nested_type == "user":
        _append_claude_user_message(
            message,
            state,
            agent_id=agent_id,
            agent_name=agent_name,
            allow_prompt_text=False,
        )


def _append_claude_user_message(
    message: JsonObject,
    state: _ParseState,
    *,
    agent_id: str | None = None,
    agent_name: str | None = None,
    allow_prompt_text: bool = True,
) -> None:
    content = message.get("content")
    texts = _extract_text_blocks(content) if allow_prompt_text else []
    if texts:
        state.begin_user_turn()
        for text in texts:
            cleaned = _strip_command_tags(text)
            if cleaned:
                state.append(
                    "user_message",
                    role="user",
                    content=cleaned,
                    agent_id=agent_id,
                    agent_name=agent_name,
                )
    for tool_result in _extract_tool_result_blocks(content):
        state.append(
            "tool_result",
            content=tool_result["content"],
            tool_output=tool_result["tool_output"],
            agent_id=agent_id,
            agent_name=agent_name,
        )


def _append_claude_assistant_message(
    message: JsonObject,
    state: _ParseState,
    *,
    agent_id: str | None = None,
    agent_name: str | None = None,
) -> None:
    content = message.get("content")
    model_used = message.get("model") if isinstance(message.get("model"), str) else None
    if isinstance(content, str) and content.strip():
        state.append(
            "assistant_message",
            role="assistant",
            content=content.strip(),
            model_used=model_used,
            agent_id=agent_id,
            agent_name=agent_name,
        )
        return
    if not isinstance(content, list):
        return
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text":
            text = block.get("text")
            if isinstance(text, str) and text.strip():
                state.append(
                    "assistant_message",
                    role="assistant",
                    content=text.strip(),
                    model_used=model_used,
                    agent_id=agent_id,
                    agent_name=agent_name,
                )
        elif block_type == "thinking":
            thinking = block.get("thinking")
            if isinstance(thinking, str) and thinking.strip():
                state.append(
                    "thinking",
                    content=thinking.strip(),
                    model_used=model_used,
                    agent_id=agent_id,
                    agent_name=agent_name,
                )
        elif block_type == "tool_use":
            tool_name = block.get("name")
            tool_input = block.get("input")
            state.append(
                "tool_use",
                tool_name=tool_name if isinstance(tool_name, str) else "unknown",
                tool_input=tool_input if isinstance(tool_input, dict) else {},
                model_used=model_used,
                agent_id=agent_id,
                agent_name=agent_name,
            )


def _append_codex_response_item(payload: object, state: _ParseState) -> None:
    if not isinstance(payload, dict):
        return
    payload_type = payload.get("type")
    if payload_type == "message":
        _append_codex_message_payload(payload, state)
        return
    if payload_type == "function_call":
        arguments = _parse_function_arguments(payload.get("arguments"))
        tool_name = payload.get("name")
        state.append(
            "tool_use",
            tool_name=tool_name if isinstance(tool_name, str) else "unknown",
            tool_input=arguments,
        )
        return
    if payload_type == "function_call_output":
        output = payload.get("output")
        tool_output = {"output": output} if isinstance(output, str) else {}
        state.append("tool_result", tool_output=tool_output, content=tool_output.get("output"))


def _append_codex_message_payload(payload: JsonObject, state: _ParseState) -> None:
    role = payload.get("role")
    content = payload.get("content")
    if not isinstance(content, list):
        return
    is_user = role == "user"
    if is_user:
        state.begin_user_turn()

    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type not in {"input_text", "output_text", "text"}:
            continue
        text = block.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        cleaned = _strip_command_tags(text) if is_user else text.strip()
        if not cleaned:
            continue
        state.append(
            "user_message" if is_user else "assistant_message",
            role="user" if is_user else "assistant",
            content=cleaned,
        )


def _get_message_content(obj: JsonObject) -> object:
    message = obj.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    return content if content is not None else ""


def _extract_text_blocks(content: object) -> list[str]:
    if isinstance(content, str):
        return [content] if content.strip() else []
    if not isinstance(content, list):
        return []
    texts: list[str] = []
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "text":
            continue
        text = block.get("text")
        if isinstance(text, str) and text.strip():
            texts.append(text)
    return texts


def _extract_tool_result_blocks(content: object) -> list[dict[str, Any]]:
    if not isinstance(content, list):
        return []
    results: list[dict[str, Any]] = []
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "tool_result":
            continue
        rendered = _render_tool_result_content(block.get("content"))
        tool_output: dict[str, Any] = {}
        tool_use_id = block.get("tool_use_id")
        if isinstance(tool_use_id, str) and tool_use_id:
            tool_output["tool_use_id"] = tool_use_id
        is_error = block.get("is_error")
        if isinstance(is_error, bool):
            tool_output["is_error"] = is_error
        if rendered is not None:
            tool_output["content"] = rendered
        results.append({"content": rendered, "tool_output": tool_output})
    return results


def _render_tool_result_content(content: object) -> str | None:
    if isinstance(content, str):
        stripped = content.strip()
        return stripped if stripped else None
    text_blocks = _extract_text_blocks(content)
    if not text_blocks:
        return None
    rendered = "\n".join(text_blocks).strip()
    return rendered or None


def _parse_function_arguments(arguments: object) -> dict[str, Any]:
    if isinstance(arguments, dict):
        return {str(key): value for key, value in arguments.items()}
    if not isinstance(arguments, str) or not arguments.strip():
        return {}
    try:
        parsed = json.loads(arguments)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _strip_command_tags(content: str) -> str:
    if content.startswith(("<local-command", "<command-")):
        return ""
    return content.strip()
