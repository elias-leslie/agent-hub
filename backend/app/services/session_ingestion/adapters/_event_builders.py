"""Internal helpers for building normalized events from transcript content blocks."""

from __future__ import annotations

import json
from typing import Any

from app.services.session_ingestion.models import NormalizedEvent

JsonObject = dict[str, object]


class _ParseState:
    """Mutable transcript parsing state."""

    def __init__(self, *, turn: int = 1, sequence: int = 0, saw_content: bool = False) -> None:
        self.turn = turn
        self.sequence = sequence
        self.events: list[NormalizedEvent] = []
        self._saw_content = saw_content

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


def append_normalized_events(obj: JsonObject, state: _ParseState) -> None:
    entry_type = obj.get("type")
    if entry_type == "progress":
        _append_claude_progress_events(obj, state)
        return
    if entry_type == "user" and not obj.get("isMeta"):
        message = obj.get("message")
        if isinstance(message, dict):
            append_claude_user_message(message, state)
        return
    if entry_type == "assistant":
        message = obj.get("message")
        if isinstance(message, dict):
            append_claude_assistant_message(message, state)
        return
    if entry_type == "response_item":
        _append_codex_response_item(obj.get("payload"), state)


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
        append_claude_assistant_message(message, state, agent_id=agent_id, agent_name=agent_name)
    elif nested_type == "user":
        append_claude_user_message(
            message, state, agent_id=agent_id, agent_name=agent_name, allow_prompt_text=False
        )


def append_claude_user_message(
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


def _append_assistant_content_block(
    block: JsonObject,
    state: _ParseState,
    model_used: str | None,
    agent_id: str | None,
    agent_name: str | None,
) -> None:
    """Emit a normalized event for a single assistant content block."""
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


def append_claude_assistant_message(
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
        if isinstance(block, dict):
            _append_assistant_content_block(block, state, model_used, agent_id, agent_name)


def _append_codex_response_item(payload: object, state: _ParseState) -> None:
    if not isinstance(payload, dict):
        return
    payload_type = payload.get("type")
    if payload_type == "message":
        _append_codex_message_payload(payload, state)
        return
    if payload_type == "function_call":
        raw_args = payload.get("arguments")
        if isinstance(raw_args, dict):
            arguments: dict[str, Any] = {str(k): v for k, v in raw_args.items()}
        elif isinstance(raw_args, str) and raw_args.strip():
            try:
                parsed_args = json.loads(raw_args)
            except json.JSONDecodeError:
                parsed_args = {}
            arguments = parsed_args if isinstance(parsed_args, dict) else {}
        else:
            arguments = {}
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


def _render_tool_result_content(content: object) -> str | None:
    if isinstance(content, str):
        stripped = content.strip()
        return stripped if stripped else None
    text_blocks = _extract_text_blocks(content)
    if not text_blocks:
        return None
    rendered = "\n".join(text_blocks).strip()
    return rendered or None


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


def _strip_command_tags(content: str) -> str:
    if content.startswith(("<local-command", "<command-")):
        return ""
    return content.strip()
