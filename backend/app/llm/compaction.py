"""Context compaction for the tool loop: a long run shortens what it sends, never what it records.

Shaped like Pi's compaction (pi-coding-agent ``core/compaction``, MIT): before a provider call, when the prompt is
within ``reserve_tokens`` of the model's context window, the oldest messages up to a cut point become one summary
message and the newest ``keep_recent_tokens`` stay verbatim.

* The prompt size is the last real usage (input + cache + output of the newest assistant message that carries one)
  plus a chars/4 estimate of the messages after it; with no usage yet it is an estimate of everything.
* The cut point is always a user or assistant message, never a tool result, so a tool call and its results stay on
  the same side of the cut.
* The system prompt (``Context.system_prompt``) and the first user message (the task) are never summarized. The
  summary goes right after them. A later compaction folds the standing summary and the messages since into a new one
  (Pi's "update" prompt), so a prefix is summarized once.
* The files the summarized tool calls read or changed are listed under the summary.
* The summarizer is injected (:data:`Summarizer`); the caller picks the model through an agent slug. A summarizer
  failure raises :class:`CompactionFailed`: the loop ends with an explicit error, history is never dropped quietly.

The loop mutates only ``Context.messages``. Persistence is separate: the session's events already hold every
original message, and the compaction itself is recorded as a ``compaction`` event (:class:`CompactionRecord`).
"""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from .types import (
    AssistantMessage,
    Context,
    Message,
    TextContent,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)

# Estimation, not policy: Pi counts one token per four characters, and a fixed cost per image block.
CHARS_PER_TOKEN = 4
IMAGE_CHARS = 4_800

SUMMARIZATION_PROMPT = """The messages above are a conversation to summarize. Create a structured context checkpoint summary that another LLM will use to continue the work.

Use this EXACT format:

## Goal
[What is the user trying to accomplish? Can be multiple items if the session covers different tasks.]

## Constraints & Preferences
- [Any constraints, preferences, or requirements mentioned by the user]
- [Or "(none)" if none were mentioned]

## Progress
### Done
- [x] [Completed tasks/changes]

### In Progress
- [ ] [Current work]

### Blocked
- [Issues preventing progress, if any]

## Key Decisions
- **[Decision]**: [Brief rationale]

## Next Steps
1. [Ordered list of what should happen next]

## Critical Context
- [Any data, examples, or references needed to continue]
- [Or "(none)" if not applicable]

Keep each section concise. Preserve exact file paths, function names, and error messages."""

UPDATE_SUMMARIZATION_PROMPT = """The messages above are NEW conversation messages to incorporate into the existing summary provided in <previous-summary> tags.

Update the existing structured summary with new information. RULES:
- PRESERVE all existing information from the previous summary
- ADD new progress, decisions, and context from the new messages
- UPDATE the Progress section: move items from "In Progress" to "Done" when completed
- UPDATE "Next Steps" based on what was accomplished
- PRESERVE exact file paths, function names, and error messages
- If something is no longer relevant, you may remove it

Use the same EXACT format as the previous summary (Goal, Constraints & Preferences, Progress with Done / In Progress / Blocked, Key Decisions, Next Steps, Critical Context). Keep each section concise."""

SUMMARY_PREFIX = (
    "The earlier part of this conversation was compacted into the summary below to fit the context window. "
    "Continue the work from it; the messages after it are exact."
)


class CompactionFailed(Exception):
    """The summary could not be made; the history was left as it was."""


@dataclass(frozen=True, slots=True)
class CompactionPolicy:
    """How a model's loop compacts. Every number is data (``Settings.llm_compaction_*``), the window is the catalog's."""

    context_window: int
    reserve_tokens: int
    keep_recent_tokens: int
    tool_result_chars: int
    read_tools: frozenset[str] = frozenset()
    write_tools: frozenset[str] = frozenset()

    @property
    def threshold(self) -> int:
        """Prompt tokens above which a provider call is preceded by a compaction."""
        return self.context_window - self.reserve_tokens


@dataclass(frozen=True, slots=True)
class SummaryRequest:
    """What the summarizer is asked: the serialized messages to fold in and, after the first time, the standing summary."""

    transcript: str
    previous_summary: str | None
    prompt: str


@dataclass(frozen=True, slots=True)
class SummaryResult:
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0


Summarizer = Callable[[SummaryRequest], Awaitable[SummaryResult]]


@dataclass(slots=True)
class CompactionRecord:
    """One compaction as it is reported and recorded: sizes, what summarized it, what it cost."""

    status: str  # "ok" | "failed"
    tokens_before: int
    tokens_after: int
    context_window: int
    threshold: int
    estimated_from: str  # "usage" (the last provider usage plus newer messages) | "estimate"
    messages_summarized: int
    messages_kept: int
    summarizer_model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0
    read_files: int = 0
    modified_files: int = 0
    error: str | None = None
    at: float = field(default_factory=time.time)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# --- Sizes -------------------------------------------------------------------------------------------------------


def _content_chars(content: str | list[Any]) -> int:
    if isinstance(content, str):
        return len(content)
    return sum(len(b.text) if isinstance(b, TextContent) else IMAGE_CHARS for b in content)


def message_tokens(message: Message) -> int:
    """Pi's estimate: characters of text, thinking and tool-call arguments over four."""
    if isinstance(message, (UserMessage, ToolResultMessage)):
        chars = _content_chars(message.content)
    else:
        chars = 0
        for block in message.content:
            if isinstance(block, TextContent):
                chars += len(block.text)
            elif isinstance(block, ToolCall):
                chars += len(block.name) + len(json.dumps(block.arguments, default=str))
            else:
                chars += len(getattr(block, "thinking", "") or "")
    return -(-chars // CHARS_PER_TOKEN)


def _overhead_tokens(context: Context) -> int:
    chars = len(context.system_prompt or "")
    for tool in context.tools or []:
        chars += len(tool.name) + len(tool.description) + len(json.dumps(tool.parameters, default=str))
    return -(-chars // CHARS_PER_TOKEN)


def _usage_tokens(message: AssistantMessage) -> int:
    usage = message.usage
    return usage.input + usage.cache_read + usage.cache_write + usage.output


def estimate_context_tokens(context: Context, trusted_from: int = 0) -> tuple[int, str]:
    """(tokens the next provider call will carry, where the figure came from).

    Only usage from an assistant message at an index of ``trusted_from`` or later counts: after a compaction the
    messages that survived were measured against the longer history.
    """
    messages = context.messages
    for index in range(len(messages) - 1, trusted_from - 1, -1):
        message = messages[index]
        measured = _usage_tokens(message) if isinstance(message, AssistantMessage) and message.stop_reason not in ("error", "aborted") else 0
        if measured > 0:
            return measured + sum(message_tokens(m) for m in messages[index + 1 :]), "usage"
    return _overhead_tokens(context) + sum(message_tokens(m) for m in messages), "estimate"


# --- Cut point ---------------------------------------------------------------------------------------------------


def _first_user_index(messages: list[Message]) -> int | None:
    return next((i for i, m in enumerate(messages) if isinstance(m, UserMessage)), None)


def find_cut_point(messages: list[Message], start: int, keep_recent_tokens: int) -> int:
    """Index where the kept tail begins; ``start`` when there is nothing before it worth summarizing.

    Walks back from the newest message until ``keep_recent_tokens`` are held, then takes the nearest user or assistant
    message at or after that point (a tool result is never a cut point, so a call and its results stay together; when
    only tool results follow the budget, the assistant message that made the calls is the cut).
    """
    cuts = [i for i in range(start, len(messages)) if isinstance(messages[i], (UserMessage, AssistantMessage))]
    if not cuts:
        return start
    held = 0
    cut = start  # the tail never reached the budget: everything after the task is recent
    for index in range(len(messages) - 1, start - 1, -1):
        held += message_tokens(messages[index])
        if held >= keep_recent_tokens:
            cut = next((c for c in cuts if c >= index), cuts[-1])
            break
    return cut


# --- Text the summarizer reads -----------------------------------------------------------------------------------


def _user_text(message: UserMessage) -> str:
    if isinstance(message.content, str):
        return message.content
    return "\n".join(b.text if isinstance(b, TextContent) else "[image]" for b in message.content)


def serialize_messages(messages: list[Message], tool_result_chars: int) -> str:
    """The messages as plain text (so the summarizer does not continue the conversation), results clipped, thinking left out."""
    parts: list[str] = []
    for message in messages:
        if isinstance(message, UserMessage):
            if text := _user_text(message):
                parts.append(f"[User]: {text}")
        elif isinstance(message, AssistantMessage):
            text = "".join(b.text for b in message.content if isinstance(b, TextContent))
            calls = [
                f"{b.name}({', '.join(f'{k}={json.dumps(v, default=str)}' for k, v in b.arguments.items())})"
                for b in message.content
                if isinstance(b, ToolCall)
            ]
            if text:
                parts.append(f"[Assistant]: {text}")
            if calls:
                parts.append(f"[Assistant tool calls]: {'; '.join(calls)}")
        else:
            body = "\n".join(b.text for b in message.content if isinstance(b, TextContent))
            if body:
                more = len(body) - tool_result_chars
                clipped = body if more <= 0 else f"{body[:tool_result_chars]}\n\n[... {more} more characters truncated]"
                parts.append(f"[Tool result]: {clipped}")
    return "\n\n".join(parts)


def _file_ops(messages: list[Message], policy: CompactionPolicy, read: set[str], modified: set[str]) -> None:
    for message in messages:
        if not isinstance(message, AssistantMessage):
            continue
        for block in message.content:
            if not isinstance(block, ToolCall) or not isinstance(path := block.arguments.get("path"), str):
                continue
            if block.name in policy.write_tools:
                modified.add(path)
            elif block.name in policy.read_tools:
                read.add(path)


def _file_lists(read: set[str], modified: set[str]) -> str:
    sections = []
    if only_read := sorted(read - modified):
        sections.append("<read-files>\n" + "\n".join(only_read) + "\n</read-files>")
    if modified:
        sections.append("<modified-files>\n" + "\n".join(sorted(modified)) + "\n</modified-files>")
    return "\n\n" + "\n\n".join(sections) if sections else ""


# --- The compactor -----------------------------------------------------------------------------------------------


class Compactor:
    """One loop's compaction state: the standing summary message, which usage can still be trusted, files seen."""

    def __init__(self, policy: CompactionPolicy, summarize: Summarizer) -> None:
        self.policy = policy
        self._summarize = summarize
        self._summary: UserMessage | None = None
        self._summary_text: str | None = None
        self._trusted_from = 0
        self._read: set[str] = set()
        self._modified: set[str] = set()

    async def compact_if_needed(self, context: Context) -> CompactionRecord | None:
        """Shorten ``context.messages`` when the next call would pass the threshold; None when nothing was done.

        Raises :class:`CompactionFailed` when the summarizer fails; the messages are untouched then.
        """
        policy = self.policy
        tokens_before, source = estimate_context_tokens(context, self._trusted_from)
        if tokens_before <= policy.threshold:
            return None
        messages = context.messages
        task = _first_user_index(messages)
        head_end = 0 if task is None else task + 1
        start = head_end + 1 if head_end < len(messages) and messages[head_end] is self._summary else head_end
        cut = find_cut_point(messages, start, policy.keep_recent_tokens)
        if cut <= start:
            return None  # everything after the task is recent already: nothing older to fold in
        prefix = messages[start:cut]
        read, modified = set(self._read), set(self._modified)
        _file_ops(prefix, policy, read, modified)
        request = SummaryRequest(
            transcript=serialize_messages(prefix, policy.tool_result_chars),
            previous_summary=self._summary_text,
            prompt=UPDATE_SUMMARIZATION_PROMPT if self._summary_text else SUMMARIZATION_PROMPT,
        )
        try:
            result = await self._summarize(request)
        except Exception as exc:
            raise CompactionFailed(f"{type(exc).__name__}: {exc}"[:500]) from exc
        text = result.text.strip()
        if not text:
            raise CompactionFailed(f"the summarizer ({result.model}) returned no text")
        summary = UserMessage(
            content=f"{SUMMARY_PREFIX}\n\n<summary>\n{text}{_file_lists(read, modified)}\n</summary>",
            timestamp=int(time.time() * 1000),
        )
        kept = messages[cut:]
        context.messages[:] = [*messages[:head_end], summary, *kept]
        self._summary, self._summary_text, self._read, self._modified = summary, text, read, modified
        self._trusted_from = len(context.messages)
        tokens_after, _ = estimate_context_tokens(context, self._trusted_from)
        return CompactionRecord(
            status="ok",
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            context_window=policy.context_window,
            threshold=policy.threshold,
            estimated_from=source,
            messages_summarized=len(prefix),
            messages_kept=len(kept),
            summarizer_model=result.model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cache_read_tokens=result.cache_read_tokens,
            cache_write_tokens=result.cache_write_tokens,
            cost_usd=result.cost_usd,
            read_files=len(read - modified),
            modified_files=len(modified),
        )

    def failure_record(self, context: Context, error: str) -> CompactionRecord:
        tokens, source = estimate_context_tokens(context, self._trusted_from)
        return CompactionRecord(
            status="failed",
            tokens_before=tokens,
            tokens_after=tokens,
            context_window=self.policy.context_window,
            threshold=self.policy.threshold,
            estimated_from=source,
            messages_summarized=0,
            messages_kept=len(context.messages),
            error=error,
        )


__all__ = [
    "CompactionFailed",
    "CompactionPolicy",
    "CompactionRecord",
    "Compactor",
    "Summarizer",
    "SummaryRequest",
    "SummaryResult",
    "estimate_context_tokens",
    "find_cut_point",
    "message_tokens",
    "serialize_messages",
]
