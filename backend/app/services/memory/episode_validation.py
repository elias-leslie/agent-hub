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
        r"(?i)\b(subtask\s+[a-z0-9-]+.*\battempts?\b|merge of task\s+[a-z0-9-]+|task-[a-z0-9]{6,})\b"
    )
    DOCUMENT_ARTIFACT_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"(?i)(document pattern for this household|source document:\s|^question:\s|^answer:\s)"
    )
    SESSION_SUMMARY_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"(?im)^\[session summary:"
    )


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
    def _detect_non_reusable_patterns(cls, content: str) -> list[str]:
        detected: list[str] = []
        if cls.HEARTBEAT_JOURNAL_PATTERN.search(content):
            detected.append("heartbeat journal")
        if cls.TASK_EXECUTION_LOG_PATTERN.search(content):
            detected.append("task execution log")
        if cls.DOCUMENT_ARTIFACT_PATTERN.search(content):
            detected.append("document-specific artifact")
        if cls.SESSION_SUMMARY_PATTERN.search(content):
            detected.append("session summary")
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
