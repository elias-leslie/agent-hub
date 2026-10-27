"""Internal helpers for building normalized events from transcript content blocks."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any

from app.llm.utils.outcomes import ProviderOutcome, outcome_details
from app.services.session_ingestion.models import NormalizedEvent

JsonObject = dict[str, object]
_SYNTHETIC_MODEL = "<synthetic>"
_WEB_CALL_RE = re.compile(r"\btools\.web__run\s*\(")
_CUA_CALL_RE = re.compile(r"\b(?:cua|tab|nodeRepl)\.[A-Za-z_][\w.]*\s*\(")
_EXEC_COMMAND_LITERAL_RE = re.compile(
    r'(?m)^[ \t]*(?:const\s+[A-Za-z_$][\w$]*\s*=\s*)?await\s+'
    r'tools\.exec_command\s*\(\s*\{\s*cmd\s*:\s*'
    r'(?P<command>"(?:\\.|[^"\\])*")',
)
_YIELDED_EXEC_RECEIPT_RE = re.compile(
    r"\AScript running with cell ID [A-Za-z0-9][A-Za-z0-9._:-]*(?:\r?\n|\Z)"
)


def _native_tool_hints(tool_name: object, arguments: dict[str, Any]) -> list[str]:
    """Label visible native call syntax without asserting a permission decision."""
    if tool_name == "exec":
        code = arguments.get("raw")
        return ["web__run"] if isinstance(code, str) and _WEB_CALL_RE.search(code) else []
    if tool_name == "js":
        code = arguments.get("code")
        return ["mcp__cua_repl.js"] if isinstance(code, str) and _CUA_CALL_RE.search(code) else []
    return []


def _command_input_digest(command: str) -> str:
    return hashlib.sha256(
        json.dumps(
            {"command": command},
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode()
    ).hexdigest()


def _strip_js_comments(source: str) -> str:
    """Remove JavaScript comments while preserving strings and line positions."""
    output: list[str] = []
    index = 0
    quote: str | None = None
    while index < len(source):
        character = source[index]
        following = source[index + 1] if index + 1 < len(source) else ''
        if quote is not None:
            output.append(
                character
                if quote != '`'
                else character if character in {'\n', '\r'} else ' '
            )
            if character == '\\' and index + 1 < len(source):
                index += 1
                escaped = source[index]
                output.append(
                    escaped
                    if quote != '`'
                    else escaped if escaped in {'\n', '\r'} else ' '
                )
            elif character == quote:
                quote = None
            index += 1
            continue
        if character in {'"', "'", '`'}:
            quote = character
            output.append(' ' if character == '`' else character)
            index += 1
            continue
        if character == '/' and following == '/':
            output.extend('  ')
            index += 2
            while index < len(source) and source[index] not in {'\n', '\r'}:
                output.append(' ')
                index += 1
            continue
        if character == '/' and following == '*':
            output.extend('  ')
            index += 2
            while index < len(source):
                if source[index] == '*' and index + 1 < len(source) and source[index + 1] == '/':
                    output.extend('  ')
                    index += 2
                    break
                output.append(source[index] if source[index] in {'\n', '\r'} else ' ')
                index += 1
            continue
        output.append(character)
        index += 1
    return ''.join(output)


def _nested_exec_commands(tool_name: object, arguments: dict[str, Any]) -> list[dict[str, str]]:
    """Extract literal unified-exec commands without evaluating wrapper source."""
    raw = arguments.get("raw")
    if tool_name != "exec" or not isinstance(raw, str):
        return []
    nested: list[dict[str, str]] = []
    for match in _EXEC_COMMAND_LITERAL_RE.finditer(_strip_js_comments(raw)):
        try:
            command = json.loads(match.group("command"))
        except json.JSONDecodeError:
            continue
        if isinstance(command, str) and command:
            nested.append({"tool_input_digest": _command_input_digest(command)})
    return nested


def _native_shell_command(command: object) -> str | None:
    if isinstance(command, str) and command:
        return command
    if isinstance(command, list) and len(command) >= 3:
        shell_flag = command[-2]
        shell_command = command[-1]
        if (
            isinstance(shell_flag, str)
            and shell_flag in {"-c", "-lc"}
            and isinstance(shell_command, str)
            and shell_command
        ):
            return shell_command
    return None


class _ParseState:
    """Mutable transcript parsing state."""

    def __init__(
        self, *, turn: int = 1, sequence: int = 0, saw_content: bool = False,
        history_start_ordinal: int | None = None, parent_thread_id: str | None = None,
        active_exec_call_ids: tuple[str, ...] = (),
        pending_exec_wrappers: tuple[dict[str, object], ...] = (),
        yielded_exec_wrapper_call_ids: tuple[str, ...] = (),
        codex_model_state: dict[str, Any] | None = None,
    ) -> None:
        self.turn = turn
        self.sequence = sequence
        self.events: list[NormalizedEvent] = []
        self._saw_content = saw_content
        self._source_id: str | None = None
        self._source_timestamp: datetime | None = None
        self._source_index = 0
        self.native_record_reference: dict[str, Any] = {}
        self.history_start_ordinal = history_start_ordinal
        self.parent_thread_id = parent_thread_id
        self.active_exec_call_ids = list(active_exec_call_ids)
        self.pending_exec_wrappers = [dict(wrapper) for wrapper in pending_exec_wrappers]
        self.yielded_exec_wrapper_call_ids = list(yielded_exec_wrapper_call_ids)
        self.codex_model_state = dict(codex_model_state or {})
        # Last real Claude Code model seen in this parse; names the model a later refusal was sent to.
        self.last_model: str | None = None

    def append_outcome(self, event_type: str, outcome: ProviderOutcome, content: str, **kwargs: Any) -> None:
        """Append an event that carries a typed provider outcome in its ``usage`` payload."""
        self.append(
            event_type, role="system" if event_type == "system_message" else None, content=content,
            usage={"provider_outcome": outcome_details(outcome)}, **kwargs,
        )

    def retain_exec_wrapper(
        self,
        call_id: str,
        nested_commands: list[dict[str, str]],
    ) -> None:
        digests = [command["tool_input_digest"] for command in nested_commands]
        if digests:
            self.pending_exec_wrappers.append({
                "call_id": call_id,
                "tool_input_digests": digests,
            })

    def resolve_exec_wrapper_result(self, call_id: str, rendered: str | None) -> None:
        matching = [
            wrapper
            for wrapper in self.pending_exec_wrappers
            if wrapper.get("call_id") == call_id
        ]
        if not matching:
            return
        if isinstance(rendered, str) and _YIELDED_EXEC_RECEIPT_RE.search(rendered):
            if call_id not in self.yielded_exec_wrapper_call_ids:
                self.yielded_exec_wrapper_call_ids.append(call_id)
            return
        self.pending_exec_wrappers = [
            wrapper
            for wrapper in self.pending_exec_wrappers
            if wrapper.get("call_id") != call_id
        ]
        if call_id in self.yielded_exec_wrapper_call_ids:
            self.yielded_exec_wrapper_call_ids.remove(call_id)

    def correlate_exec_wrapper(self, command: object) -> tuple[str | None, bool]:
        shell_command = _native_shell_command(command)
        if shell_command is None:
            return None, False
        digest = _command_input_digest(shell_command)
        candidates: list[dict[str, object]] = []
        call_ids: set[str] = set()
        matching_occurrences = 0
        for wrapper in self.pending_exec_wrappers:
            digests = wrapper.get("tool_input_digests")
            call_id = wrapper.get("call_id")
            if not isinstance(digests, list) or digest not in digests:
                continue
            candidates.append(wrapper)
            matching_occurrences += digests.count(digest)
            if isinstance(call_id, str):
                call_ids.add(call_id)
        if len(call_ids) != 1 or matching_occurrences != 1:
            return None, bool(candidates)
        call_id = next(iter(call_ids))
        for wrapper in candidates:
            if wrapper.get("call_id") != call_id:
                continue
            digests = wrapper.get("tool_input_digests")
            if not isinstance(digests, list):
                continue
            digests.remove(digest)
            if not digests:
                self.pending_exec_wrappers.remove(wrapper)
                if call_id in self.yielded_exec_wrapper_call_ids:
                    self.yielded_exec_wrapper_call_ids.remove(call_id)
            break
        return call_id, True

    def set_source(self, obj: JsonObject, fallback_id: str | None = None) -> None:
        payload = obj.get("payload")
        native_id = payload.get("id") if isinstance(payload, dict) else None
        item = payload.get("item") if isinstance(payload, dict) else None
        if (
            (not isinstance(native_id, str) or not native_id)
            and isinstance(item, dict)
            and item.get("type") == "CommandExecution"
            and isinstance(item.get("id"), str)
            and item["id"]
        ):
            digest = hashlib.sha256(
                json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
            ).hexdigest()[:16]
            native_id = f"{item['id']}:{digest}"
        if not isinstance(native_id, str) or not native_id:
            native_id = fallback_id
        self._source_id = f"{obj.get('type')}:{native_id}" if native_id else None
        timestamp = obj.get("timestamp")
        try:
            self._source_timestamp = (
                datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                if isinstance(timestamp, str)
                else None
            )
        except ValueError:
            self._source_timestamp = None
        self._source_index = 0

    def begin_user_turn(self) -> None:
        if self._saw_content:
            self.turn += 1
        self.sequence = 0

    def append(self, event_type: str, **kwargs: Any) -> None:
        call_id = kwargs.get("call_id")
        if (
            event_type == "tool_use"
            and isinstance(call_id, str)
            and call_id
            and call_id not in self.active_exec_call_ids
        ):
            self.active_exec_call_ids.append(call_id)
        elif (
            event_type == "tool_result"
            and isinstance(call_id, str)
            and call_id
            and call_id in self.active_exec_call_ids
        ):
            self.active_exec_call_ids.remove(call_id)
        self.sequence += 1
        self._saw_content = True
        self._source_index += 1
        if self._source_id:
            source_id = f"{self._source_id}:{self._source_index}"
            if len(source_id) > 255:
                source_id = f"{source_id[:190]}:{hashlib.sha256(source_id.encode()).hexdigest()}"
            kwargs.setdefault("source_event_id", source_id)
        kwargs.setdefault("source_timestamp", self._source_timestamp)
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
    if entry_type == "session_meta":
        payload = obj.get("payload")
        if isinstance(payload, dict):
            own_thread = state.codex_model_state.get("session_id")
            if own_thread and payload.get("id") != own_thread:
                state.codex_model_state["history_owner_thread_id"] = payload.get("id")
                return  # Copied headers cannot replace own lineage/boundaries.
            start = payload.get("subagent_history_start_ordinal")
            if isinstance(start, int) and not isinstance(start, bool) and start >= 0:
                state.history_start_ordinal = start
            parent = payload.get("parent_thread_id")
            if isinstance(parent, str) and parent:
                state.parent_thread_id = parent
        return
    ordinal = obj.get("ordinal")
    if (
        state.history_start_ordinal is not None
        and isinstance(ordinal, int)
        and ordinal < state.history_start_ordinal
    ):
        return  # Child transcripts can include inherited parent history.
    payload = obj.get("payload")
    if isinstance(payload, dict) and (
        payload.get("thread_id") == state.codex_model_state.get("session_id")
        or (state.history_start_ordinal is not None and isinstance(ordinal, int) and ordinal >= state.history_start_ordinal)
    ):
        state.codex_model_state.pop("history_owner_thread_id", None)
    if entry_type == "token_usage_record":
        _append_codex_usage_record(obj.get("payload"), state)
        return
    if entry_type == "event_msg":
        payload = obj.get("payload")
        if isinstance(payload, dict):
            _append_codex_event_message(payload, state)
        return
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
            append_claude_assistant_message(message, state, request_id=obj.get("requestId"))
        return
    if entry_type == "system" and obj.get("subtype") == "model_refusal_fallback":
        _append_claude_model_fallback(obj, state)
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
            call_id=tool_result["call_id"],
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
        call_id = block.get("id")
        state.append(
            "tool_use",
            tool_name=tool_name if isinstance(tool_name, str) else "unknown",
            call_id=call_id if isinstance(call_id, str) and call_id else None,
            tool_input=tool_input if isinstance(tool_input, dict) else {},
            model_used=model_used,
            agent_id=agent_id,
            agent_name=agent_name,
        )


def _text_field(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _append_claude_model_fallback(obj: JsonObject, state: _ParseState) -> None:
    """A refused request that Claude Code retried on another model."""
    original = _text_field(obj.get("originalModel")) or state.last_model or "unknown"
    fallback = _text_field(obj.get("fallbackModel"))
    category = _text_field(obj.get("apiRefusalCategory"))
    state.last_model = fallback or state.last_model
    state.append_outcome(
        "system_message",
        ProviderOutcome(
            kind="substituted", requested_model=original, served_model=fallback, category=category,
            explanation=_text_field(obj.get("apiRefusalExplanation")),
            request_id=_text_field(obj.get("requestId")),
        ),
        f"Model switched from {original} to {fallback or 'another model'}"
        + (f" after a {category} refusal." if category else " after a refusal."),
    )


def append_claude_assistant_message(
    message: JsonObject,
    state: _ParseState,
    *,
    agent_id: str | None = None,
    agent_name: str | None = None,
    request_id: object = None,
) -> None:
    content = message.get("content")
    model_used = _text_field(message.get("model"))
    synthetic = model_used == _SYNTHETIC_MODEL
    if synthetic:
        # Claude Code's own placeholder turn, never a model that answered.
        model_used = None
    elif model_used:
        state.last_model = model_used
    if message.get("stop_reason") == "refusal":
        details = message.get("stop_details")
        details = details if isinstance(details, dict) else {}
        category = _text_field(details.get("category"))
        explanation = _text_field(details.get("explanation"))
        state.append_outcome(
            "error",
            ProviderOutcome(
                kind="refused", requested_model=state.last_model or "unknown", category=category,
                explanation=explanation, request_id=_text_field(request_id),
            ),
            explanation or f"The provider refused this request{f' ({category})' if category else ''}.",
            model_used=model_used, agent_id=agent_id, agent_name=agent_name,
        )
    if synthetic:
        return  # The placeholder text only restates the refusal.
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


def _append_codex_agent_message(payload: JsonObject, state: _ParseState) -> None:
    """Retain native parent/child messages in the session that received them."""
    author = payload.get("author")
    content = payload.get("content")
    if not isinstance(author, str) or not author or not isinstance(content, list):
        return
    texts: list[str] = []
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "input_text":
            continue
        text = block.get("text")
        if isinstance(text, str) and text.strip():
            texts.append(text.strip())
    if not texts:
        return
    if state.parent_thread_id:
        state.begin_user_turn()
        state.append(
            "user_message",
            role="user",
            content="\n".join(texts),
            agent_id=author,
        )
        return
    state.append(
        "subagent_result",
        role="assistant",
        content="\n".join(texts),
        agent_id=author,
    )


def _append_codex_response_item(payload: object, state: _ParseState) -> None:
    if not isinstance(payload, dict):
        return
    payload_type = payload.get("type")
    if payload_type == "agent_message":
        _append_codex_agent_message(payload, state)
        return
    if payload_type == "message":
        _append_codex_message_payload(payload, state)
        return
    if payload_type in {"function_call", "custom_tool_call"}:
        raw_args = payload.get("arguments") if payload_type == "function_call" else payload.get("input")
        if isinstance(raw_args, dict):
            arguments: dict[str, Any] = {str(k): v for k, v in raw_args.items()}
        elif isinstance(raw_args, str) and raw_args.strip():
            try:
                parsed_args = json.loads(raw_args)
            except json.JSONDecodeError:
                parsed_args = None
            arguments = parsed_args if isinstance(parsed_args, dict) else {"raw": raw_args, "format": "opaque"}
        else:
            arguments = {}
        tool_name = payload.get("name")
        native_tool_hints = _native_tool_hints(tool_name, arguments)
        if native_tool_hints:
            arguments["native_tool_hints"] = native_tool_hints
        nested_exec_commands = _nested_exec_commands(tool_name, arguments)
        if nested_exec_commands:
            arguments["nested_exec_commands"] = nested_exec_commands
        call_id = payload.get("call_id")
        if isinstance(call_id, str) and call_id:
            arguments = {**arguments, "call_id": call_id}
        state.append(
            "tool_use",
            tool_name=tool_name if isinstance(tool_name, str) else "unknown",
            call_id=call_id if isinstance(call_id, str) and call_id else None,
            tool_input=arguments,
        )
        if isinstance(call_id, str) and call_id and nested_exec_commands:
            state.retain_exec_wrapper(call_id, nested_exec_commands)
        return
    if payload_type in {"function_call_output", "custom_tool_call_output"}:
        output = payload.get("output")
        text_parts: list[str] = []
        opaque_blocks = 0
        if isinstance(output, str):
            text_parts.append(output)
        elif isinstance(output, list):
            for block in output:
                if isinstance(block, dict) and isinstance(block.get("text"), str):
                    text_parts.append(block["text"])
                else:
                    opaque_blocks += 1
        rendered = "\n".join(text_parts) if text_parts else None
        tool_output: dict[str, Any] = {}
        if rendered is not None:
            tool_output["output"] = rendered
        if opaque_blocks:
            tool_output["opaque_blocks"] = opaque_blocks
        call_id = payload.get("call_id")
        if isinstance(call_id, str) and call_id:
            tool_output["call_id"] = call_id
        state.append(
            "tool_result", call_id=call_id if isinstance(call_id, str) and call_id else None,
            tool_output=tool_output, content=rendered,
        )
        if isinstance(call_id, str) and call_id:
            state.resolve_exec_wrapper_result(call_id, rendered)


def _timestamp_from_milliseconds(value: object) -> datetime | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        return None
    try:
        return datetime.fromtimestamp(value / 1000, tz=UTC)
    except (OSError, OverflowError, ValueError):
        return None


def _command_duration_ms(
    item: JsonObject,
    started_at: datetime | None,
    completed_at: datetime | None,
) -> int | None:
    if started_at is not None and completed_at is not None:
        return max(0, round((completed_at - started_at).total_seconds() * 1000))
    duration = item.get("duration")
    if not isinstance(duration, dict):
        return None
    seconds = duration.get("secs")
    nanos = duration.get("nanos")
    if (
        not isinstance(seconds, int)
        or isinstance(seconds, bool)
        or seconds < 0
        or not isinstance(nanos, int)
        or isinstance(nanos, bool)
        or not 0 <= nanos < 1_000_000_000
    ):
        return None
    return seconds * 1000 + round(nanos / 1_000_000)


def _append_codex_command_execution(payload: JsonObject, state: _ParseState) -> None:
    item = payload.get("item")
    if not isinstance(item, dict) or item.get("type") != "CommandExecution":
        return
    call_id = item.get("id")
    command = item.get("command")
    valid_command = isinstance(command, str) or (
        isinstance(command, list)
        and all(isinstance(part, str) for part in command)
    )
    if not isinstance(call_id, str) or not call_id:
        state.append("error", content="Native command execution is missing its identity.")
        return
    if not valid_command:
        state.append("error", content=f"Native command execution {call_id} is missing its command.")
        return

    started_at = _timestamp_from_milliseconds(payload.get("started_at_ms"))
    completed_at = _timestamp_from_milliseconds(payload.get("completed_at_ms"))
    if started_at is None or completed_at is None or completed_at < started_at:
        state.append("error", content=f"Native command execution {call_id} has invalid timestamps.")
        started_at = completed_at = None

    status = item.get("status")
    exit_code = item.get("exit_code")
    if not isinstance(status, str) or not status:
        state.append("error", content=f"Native command execution {call_id} is missing its status.")
    if not isinstance(exit_code, int) or isinstance(exit_code, bool):
        state.append("error", content=f"Native command execution {call_id} is missing its exit code.")
    output_present = any(
        isinstance(item.get(key), str)
        for key in ("stdout", "stderr", "aggregated_output", "formatted_output")
    )
    if not output_present:
        state.append("error", content=f"Native command execution {call_id} is missing its output.")

    tool_input: dict[str, Any] = {"command": command}
    for key in ("cwd", "source"):
        value = item.get(key)
        if isinstance(value, str) and value:
            tool_input[key] = value
    wrapper_call_id, exact_wrapper_candidate = state.correlate_exec_wrapper(command)
    if wrapper_call_id is not None:
        tool_input["wrapper_candidate_call_id"] = wrapper_call_id
        tool_input["wrapper_correlation"] = "nested_command_digest"
    elif not exact_wrapper_candidate and len(state.active_exec_call_ids) == 1:
        tool_input["wrapper_candidate_call_id"] = state.active_exec_call_ids[0]
        tool_input["wrapper_correlation"] = "single_open_exec"

    tool_output: dict[str, Any] = {}
    for key in ("stdout", "stderr"):
        value = item.get(key)
        if isinstance(value, str):
            tool_output[key] = value
    if not tool_output:
        fallback = item.get("aggregated_output")
        if not isinstance(fallback, str):
            fallback = item.get("formatted_output")
        if isinstance(fallback, str):
            tool_output["output"] = fallback
    if isinstance(status, str):
        tool_output["status"] = status
    if isinstance(exit_code, int) and not isinstance(exit_code, bool):
        tool_output["exit_code"] = exit_code
    for key in ("truncated", "output_truncated"):
        if item.get(key) is True:
            tool_output[key] = True
    tool_output["is_error"] = (
        not isinstance(status, str)
        or status not in {"completed", "success", "succeeded"}
        or not isinstance(exit_code, int)
        or isinstance(exit_code, bool)
        or exit_code != 0
    )
    evidence = state.codex_model_state.get("evidence") or {}
    state.codex_model_state["command_position"] = state.codex_model_state.get("command_position", 0) + 1
    native_observation = {
        "position": state.codex_model_state["command_position"],
        "thread_id": state.codex_model_state.get("session_id") or "unknown",
        "turn_id": payload.get("turn_id") or evidence.get("turn_id"),
        "item_id": call_id,
        "identity_quality": "durable",
        "origin": "rollout_record",
        "kind": "command_execution",
        "history_owner_thread_id": state.codex_model_state.get("history_owner_thread_id"),
        "payload": dict(payload),
        "source_reference": dict(state.native_record_reference),
        "aliases": [{"kind": "transcript_runtime_session_id", "value": state.codex_model_state["native_session_id"]}]
        if state.codex_model_state.get("native_session_id") else [],
    }
    duration_ms = _command_duration_ms(item, started_at, completed_at)
    state.append(
        "tool_use",
        tool_name="Bash",
        call_id=call_id,
        tool_input=tool_input,
        source_timestamp=started_at,
    )
    state.append(
        "tool_result",
        call_id=call_id,
        tool_output=tool_output,
        native_observation=native_observation,
        duration_ms=duration_ms,
        source_timestamp=completed_at,
    )


def _append_codex_event_message(payload: JsonObject, state: _ParseState) -> None:
    if payload.get("type") == "token_count":
        _append_codex_token_counter(payload, state)
    elif payload.get("type") == "item_completed":
        _append_codex_command_execution(payload, state)
    elif payload.get("type") == "task_complete":
        error = payload.get("error")
        if not isinstance(error, dict):
            return
        message = error.get("message")
        code = error.get("codex_error_info")
        if not isinstance(message, str) or not message.strip():
            return
        # Only the public error fields belong in the timeline. Native payloads
        # can also contain encrypted or otherwise opaque provider material.
        details = {}
        if isinstance(code, str) and code:
            details["codex_error_info"] = code
            message = f"{code}: {message}"
        turn_id = payload.get("turn_id")
        if isinstance(turn_id, str) and turn_id:
            details["turn_id"] = turn_id
        state.append("error", content=message, tool_output=details or None)


_USAGE_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cached_input_tokens",
    "cache_write_input_tokens",
    "reasoning_output_tokens",
)


def _usage_counts(raw: object) -> dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    return {
        field: value
        for field in _USAGE_FIELDS
        if isinstance((value := raw.get(field)), int) and not isinstance(value, bool) and value >= 0
    }


def _append_codex_usage_record(payload: object, state: _ParseState) -> None:
    if not isinstance(payload, dict):
        return
    response_id = payload.get("response_id")
    counts = _usage_counts(payload.get("usage"))
    if counts:
        usage: dict[str, Any] = {"scope": "response", "source": "codex.token_usage_record.usage", **counts}
        for key in ("response_id", "turn_id", "root_turn_id", "thread_id", "session_id"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                usage[key] = value
        if state.parent_thread_id:
            usage["parent_thread_id"] = state.parent_thread_id
        if isinstance(response_id, str) and response_id:
            state._source_id = f"response_usage:{response_id}"
        state.append("usage", usage=usage)
    for scope, key in (("turn", "turn_token_usage"), ("thread", "thread_token_usage")):
        counts = _usage_counts(payload.get(key))
        if counts:
            state.append(
                "usage_counter",
                usage={"scope": scope, "source": f"codex.token_usage_record.{key}", **counts},
            )


def _append_codex_token_counter(payload: JsonObject, state: _ParseState) -> None:
    info = payload.get("info")
    if not isinstance(info, dict):
        return
    counts = _usage_counts(info.get("total_token_usage"))
    if counts:
        state.append(
            "usage_counter",
            usage={"scope": "thread", "source": "codex.event_msg.token_count.total_token_usage", **counts},
        )


def _append_codex_message_payload(payload: JsonObject, state: _ParseState) -> None:
    role = payload.get("role")
    event_type = {
        "user": "user_message",
        "assistant": "assistant_message",
        "developer": "system_message",
        "system": "system_message",
    }.get(role) if isinstance(role, str) else None
    if event_type is None:
        return
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
            event_type,
            role=role,
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
        results.append({
            "call_id": tool_use_id if isinstance(tool_use_id, str) and tool_use_id else None,
            "content": rendered,
            "tool_output": tool_output,
        })
    return results


def _strip_command_tags(content: str) -> str:
    if content.startswith(("<local-command", "<command-")):
        return ""
    return content.strip()
