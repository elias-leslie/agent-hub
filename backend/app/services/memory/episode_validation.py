"""Episode validation utilities."""

from __future__ import annotations

import re
from typing import ClassVar


class EpisodeValidationError(Exception):
    """Raised when episode content fails validation."""

    def __init__(self, message: str, detected_patterns: list[str]):
        self.message = message
        self.detected_patterns = detected_patterns
        super().__init__(message)


class EpisodeValidator:
    """Validates memory records and their suitability for long-term storage."""

    HEARTBEAT_JOURNAL_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"(?im)^(##\s*heartbeat:|\[auto\]\s)"
    )
    TASK_EXECUTION_LOG_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"(?i)\b(merge of task\s+[a-z0-9-]+|task-[a-z0-9]{6,})\b"
    )
    # ``subtask <id> ... attempt(s)`` on one line is matched in two linear steps
    # (see ``_has_subtask_attempt_log``) rather than ``subtask\s+[a-z0-9-].*\battempts?``,
    # which rescans to end of line from every ``subtask`` token (quadratic).
    SUBTASK_START_PATTERN: ClassVar[re.Pattern[str]] = re.compile(r"(?i)\bsubtask\s+[a-z0-9-]")
    ATTEMPTS_PATTERN: ClassVar[re.Pattern[str]] = re.compile(r"(?i)\battempts?\b")
    DOCUMENT_ARTIFACT_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"(?i)(document pattern for this household|source document:\s|^question:\s|^answer:\s)"
    )
    SESSION_SUMMARY_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"(?im)^\[session summary:"
    )
    # Line shapes of pasted tool output (tracebacks, shell sessions, test runners,
    # st status tags). Anchored at the line start, so each match attempt stays linear.
    TOOL_OUTPUT_LINE_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"^(?:Traceback \(most recent call last\):"
        r'|\s*File "[^"\n]*", line \d+'
        r"|(?:\$|>>>|\u276f) \S"
        r"|(?:FAILED|PASSED|ERROR) \S+::"
        r"|E {2,}\S"
        r"|=+ [^=\n]*\b(?:passed|failed|errors?)\b"
        r"|[A-Z][A-Z_]+(?:\[\d+\])?:(?:OK|FAIL|PASS|SKIP|ERROR|BLOCKED)\b)"
    )
    TOOL_OUTPUT_MIN_LINES: ClassVar[int] = 3
    # A compact high-tier memory that suddenly balloons is almost always a dump.
    COMPACT_TIERS: ClassVar[frozenset[str]] = frozenset({"mandate", "guardrail"})
    COMPACT_GROWTH_FACTOR: ClassVar[int] = 3
    COMPACT_GROWTH_MIN_CHARS: ClassVar[int] = 1000


    @classmethod
    def validate_content(cls, content: str, tier: str | None = None) -> None:
        """Validate record shape without prescribing a writing style."""
        if tier and tier not in {"mandate", "guardrail", "reference", "archive"}:
            raise EpisodeValidationError(
                message=f"Unsupported memory tier {tier!r}.",
                detected_patterns=["Unsupported Tier"],
            )
        if not content.strip():
            raise EpisodeValidationError(
                message="Memory content must not be empty.",
                detected_patterns=["Empty Content"],
            )

    @classmethod
    def validate_content_simple(cls, content: str) -> str | None:
        """Return a content-validation error for generated learnings."""
        try:
            cls.validate_content(content)
        except EpisodeValidationError as exc:
            return str(exc)
        return None

    @classmethod
    def validate_reusability(cls, content: str) -> None:
        """Validate that content is reusable memory rather than an operational log."""
        detected = cls._detect_non_reusable_patterns(content)
        if detected:
            raise EpisodeValidationError(
                message=(
                    "Episode is not reusable long-term memory. Store operational logs, "
                    "heartbeat journals, session summaries, and document-specific app state "
                    "in project/session data instead. "
                    f"Detected patterns: {', '.join(repr(pattern) for pattern in detected)}"
                ),
                detected_patterns=detected,
            )

    @classmethod
    def validate_reusability_simple(cls, content: str) -> str | None:
        """Return an error message when content looks like non-reusable operational data."""
        detected = cls._detect_non_reusable_patterns(content)
        if not detected:
            return None
        return (
            "Content is not reusable long-term memory. Store operational logs, heartbeat "
            "journals, session summaries, and document-specific app state in project/session "
            f"data instead. Detected patterns: {', '.join(repr(pattern) for pattern in detected)}"
        )

    @classmethod
    def looks_like_tool_output(cls, content: str) -> bool:
        """Return True when content carries pasted terminal/tool transcript lines."""
        if "\x1b[" in content:
            return True
        hits = 0
        for line in content.splitlines():
            if cls.TOOL_OUTPUT_LINE_PATTERN.match(line):
                hits += 1
                if hits >= cls.TOOL_OUTPUT_MIN_LINES:
                    return True
        return False

    @classmethod
    def validate_update(cls, content: str, *, previous: str | None, tier: str) -> None:
        """Reject updates that turn a memory into a log, a tool-output dump or a balloon.

        The reusability detectors run only on lines the update adds, so an older
        memory that already matches one can still be edited.
        """
        if cls.looks_like_tool_output(content):
            raise EpisodeValidationError(
                message="Update looks like pasted tool output or a transcript. Write the reusable "
                "rule itself; keep raw output in task/session records.",
                detected_patterns=["tool output transcript"],
            )
        kept = set((previous or "").splitlines())
        added = "\n".join(line for line in content.splitlines() if line not in kept)
        if added:
            cls.validate_reusability(added)
        if tier in cls.COMPACT_TIERS and previous:
            growth = len(content) - len(previous)
            if growth > cls.COMPACT_GROWTH_MIN_CHARS and len(content) > cls.COMPACT_GROWTH_FACTOR * len(previous):
                raise EpisodeValidationError(
                    message=f"Update grows a compact {tier} memory from {len(previous)} to {len(content)} "
                    "chars. Keep it terse, or move the explanation to the wiki.",
                    detected_patterns=["compact memory growth"],
                )

    @classmethod
    def _has_subtask_attempt_log(cls, content: str) -> bool:
        """Return True when ``subtask <id>`` is followed by ``attempt(s)`` on the same line.

        Equivalent to ``\\bsubtask\\s+[a-z0-9-].*\\battempts?\\b`` (``.`` stops at
        newlines, ``\\s+`` may cross them). Each line tail is scanned for
        ``attempts`` at most once, so the check stays linear.
        """
        checked_until = -1
        position = 0
        while (start := cls.SUBTASK_START_PATTERN.search(content, position)) is not None:
            tail_start = start.end()
            # The id character may begin the next "subtask" token, so resume just past this start.
            position = start.start() + 1
            if tail_start <= checked_until:
                # Same line tail as an earlier candidate, already known to lack "attempts".
                continue
            line_end = content.find("\n", tail_start)
            if line_end < 0:
                line_end = len(content)
            if cls.ATTEMPTS_PATTERN.search(content, tail_start, line_end):
                return True
            checked_until = line_end
        return False

    @classmethod
    def _detect_non_reusable_patterns(cls, content: str) -> list[str]:
        detected: list[str] = []
        if cls.HEARTBEAT_JOURNAL_PATTERN.search(content):
            detected.append("heartbeat journal")
        if cls.TASK_EXECUTION_LOG_PATTERN.search(content) or cls._has_subtask_attempt_log(content):
            detected.append("task execution log")
        if cls.DOCUMENT_ARTIFACT_PATTERN.search(content):
            detected.append("document-specific artifact")
        if cls.SESSION_SUMMARY_PATTERN.search(content):
            detected.append("session summary")
        if cls.looks_like_tool_output(content):
            detected.append("tool output transcript")
        return detected

    @classmethod
    def validate_summary(cls, summary: str) -> None:
        """
        Validate summary length.

        Args:
            summary: Episode summary

        Raises:
            EpisodeValidationError: If summary is too short or too long
        """
        if not summary:
            raise EpisodeValidationError(
                message="Summary is required.",
                detected_patterns=["Missing Summary"],
            )

        if len(summary) < 10:
            raise EpisodeValidationError(
                message=f"Summary is too short ({len(summary)} chars). "
                "Must be at least 10 characters.",
                detected_patterns=["Summary Too Short"],
            )

        if len(summary) > 40:
            raise EpisodeValidationError(
                message=f"Summary is too long ({len(summary)} chars). "
                "Keep it under 40 characters for the index.",
                detected_patterns=["Summary Too Long"],
            )
