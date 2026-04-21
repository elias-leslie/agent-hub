"""Shared policy for user-facing completion closeouts."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from app.services.memory.citation_parser import extract_summary_tag_strings
from app.services.session_display_summary import clean_display_summary_text

if TYPE_CHECKING:
    from app.adapters.base import Message


_TOOL_PLACEHOLDER_CLOSEOUTS = frozenset({"Mode: task", "Mode: campaign"})
_MAX_FALLBACK_SUMMARIES = 8
_HEARTBEAT_CLOSEOUT_HEADERS = frozenset({"HEARTBEAT_ACTION", "HEARTBEAT_OK"})

CloseoutAction = Literal["none", "recover", "fallback"]
CloseoutIssue = Literal["empty", "tool_placeholder"]


def _is_valid_heartbeat_summary_only_closeout(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    if len(lines) != 2 or lines[0] not in _HEARTBEAT_CLOSEOUT_HEADERS:
        return False
    summary_tags = extract_summary_tag_strings(lines[1])
    return len(summary_tags) == 1 and lines[1] == summary_tags[0]


@dataclass(frozen=True)
class CloseoutPlan:
    """Decision for how to finish a completion."""

    action: CloseoutAction
    issue: CloseoutIssue | None = None
    prompt: str | None = None
    progress_status: str | None = None
    progress_message: str | None = None
    fallback_reason: str | None = None


def detect_closeout_issue(
    content: str | None,
    *,
    tool_calls_count: int,
) -> CloseoutIssue | None:
    """Classify whether the closeout is missing or low signal."""
    text = (content or "").strip()
    if not text:
        return "empty"
    if tool_calls_count > 0 and "[[P:" in text and "[[S:" not in text:
        return "empty"
    if tool_calls_count > 0 and _is_valid_heartbeat_summary_only_closeout(text):
        return None
    cleaned = clean_display_summary_text(text)
    if not cleaned:
        return "empty"
    if tool_calls_count > 0 and cleaned in _TOOL_PLACEHOLDER_CLOSEOUTS:
        return "tool_placeholder"
    return None


def plan_user_facing_closeout(
    content: str | None,
    *,
    tool_calls_count: int,
    allow_recovery: bool,
    recovery_used: bool,
    tool_result_summaries: Sequence[str] | None = None,
) -> CloseoutPlan:
    """Decide whether to recover, fallback, or accept the closeout."""
    issue = detect_closeout_issue(content, tool_calls_count=tool_calls_count)
    if issue is None:
        return CloseoutPlan(action="none")

    if allow_recovery and not recovery_used:
        return CloseoutPlan(
            action="recover",
            issue=issue,
            prompt=build_closeout_recovery_prompt(
                content,
                tool_calls_count=tool_calls_count,
                tool_result_summaries=tool_result_summaries,
            ),
            progress_status="closeout_recovery",
            progress_message=_build_recovery_message(issue),
        )

    if tool_calls_count > 0:
        reason = "tool_closeout_recovery_failed" if recovery_used else "tool_closeout_recovery_unavailable"
        return CloseoutPlan(
            action="fallback",
            issue=issue,
            progress_status="closeout_fallback",
            progress_message="Using deterministic tool summary after closeout recovery was unavailable or failed",
            fallback_reason=reason,
        )

    return CloseoutPlan(action="none", issue=issue)


def build_closeout_recovery_prompt(
    content: str | None,
    *,
    tool_calls_count: int,
    tool_result_summaries: Sequence[str] | None = None,
) -> str:
    """Build the shared recovery prompt for one final user-facing closeout."""
    lines = [
        "<system-final-response>",
        "You have finished the work but have not produced a usable final user-facing response.",
    ]
    text = (content or "").strip()
    if text:
        lines.append(f"Current incomplete closeout: {text}")
    if tool_calls_count > 0:
        lines.append("Write the final response using the completed tool results below.")
        summaries = list(tool_result_summaries or [])[:_MAX_FALLBACK_SUMMARIES]
        if summaries:
            lines.append("Captured observations:")
            lines.extend(f"- {summary}" for summary in summaries)
        else:
            lines.append("No compact tool summaries were captured; rely on the conversation context.")
    else:
        lines.append("Write the final response now.")
    lines.extend(
        [
            "If no changes were needed, say so plainly.",
            "If changes were made, summarize the exact changes and evidence.",
            "Do not call more tools unless a missing fact blocks the response.",
            "</system-final-response>",
        ]
    )
    return "\n".join(lines)


def build_tool_closeout_fallback(
    content: str | None,
    tool_result_summaries: Sequence[str],
) -> str:
    """Replace a low-signal tool closeout with a deterministic summary."""
    header = (content or "").strip() or "Tool run"
    lines = [
        header,
        "",
        "Tool execution completed, but the agent did not provide a usable final summary.",
        "Captured observations:",
    ]
    summaries = list(tool_result_summaries)[:_MAX_FALLBACK_SUMMARIES]
    if summaries:
        lines.extend(f"- {summary}" for summary in summaries)
    else:
        lines.append("- Tool calls completed; inspect session events for detailed outputs.")
    return "\n".join(lines)


def detached_agent_hub_rebuild_closeout(
    *,
    project_id: str | None,
    tool_name: str,
    tool_input: dict[str, object],
    tool_content: str,
    agent_slug: str | None,
    external_id: str | None,
) -> str | None:
    """Return a deterministic closeout when a detached Agent Hub rebuild was queued."""
    if project_id != "agent-hub" or tool_name.lower() != "bash":
        return None

    command = str(tool_input.get("command") or "").lower()
    if "agent-hub" not in command or "--detach" not in command:
        return None
    if "rebuild.sh" not in command and "restart.sh" not in command:
        return None

    output = tool_content.lower()
    if "detached rebuild queued" not in output and "detached restart queued" not in output:
        return None

    unit_line = next(
        (line.strip() for line in str(tool_content).splitlines() if "Running as unit:" in line),
        None,
    )
    unit_name = unit_line.removeprefix("Running as unit:").strip() if unit_line else None
    unit_note = f" as {unit_name}" if unit_name else ""
    if agent_slug == "persona":
        return (
            f"HEARTBEAT_ACTION — Detached Agent Hub rebuild queued{unit_note}. "
            "Post-restart verification is deferred to a fresh session.\n"
            "[[P:started:ending the heartbeat after queueing a detached Agent Hub rebuild]]\n"
            f"[[P:decision:queued detached Agent Hub rebuild{unit_note} and ended before "
            "post-restart verification]]\n"
            "[[S:partial:Queued detached Agent Hub rebuild; a fresh post-restart session "
            "must verify health and task completion.]]"
        )
    if external_id and str(external_id).startswith("task-"):
        return (
            f"Detached Agent Hub rebuild queued{unit_note}. "
            "This session is ending before post-restart verification.\n"
            "[[P:started:ending the task session after queueing a detached Agent Hub rebuild]]\n"
            f"[[P:decision:queued detached Agent Hub rebuild{unit_note} and ended before "
            "post-restart verification]]\n"
            "[[S:partial:Queued detached Agent Hub rebuild; a fresh post-restart session "
            "must verify health and task completion.]]"
        )
    if unit_line:
        return (
            "Detached Agent Hub rebuild queued successfully.\n"
            f"{unit_line}\n"
            "[[S:partial:Queued detached Agent Hub rebuild; a fresh post-restart session "
            "must verify health and task completion.]]"
        )
    return (
        "Detached Agent Hub rebuild queued successfully.\n"
        "[[S:partial:Queued detached Agent Hub rebuild; a fresh post-restart session "
        "must verify health and task completion.]]"
    )


def append_closeout_turn(
    messages_for_adapter: list[Message],
    messages_dict: list[dict[str, str]] | None,
    assistant_content: str | None,
    prompt: str,
) -> None:
    """Append the current assistant output and recovery prompt as a final turn."""
    from app.adapters.base import Message

    text = assistant_content or ""
    messages_for_adapter.append(Message(role="assistant", content=text))
    messages_for_adapter.append(Message(role="user", content=prompt))
    if messages_dict is not None:
        messages_dict.append({"role": "assistant", "content": text})
        messages_dict.append({"role": "user", "content": prompt})


def _build_recovery_message(issue: CloseoutIssue) -> str:
    if issue == "tool_placeholder":
        return "Agent ended tool work with a placeholder closeout; requesting one final user-facing summary"
    return "Agent ended without a user-facing response; requesting one final closeout turn"
