"""Episode validation utilities."""

from __future__ import annotations

import re
from typing import ClassVar

from app.services.compactness import CompactnessValidationError, validate_compactness


class EpisodeValidationError(Exception):
    """Raised when episode content fails validation."""

    def __init__(self, message: str, detected_patterns: list[str]):
        self.message = message
        self.detected_patterns = detected_patterns
        super().__init__(message)


class EpisodeValidator:
    """Validates episode content for quality and conciseness."""

    ANY_HEADER_PATTERN: ClassVar[re.Pattern[str]] = re.compile(r"^\*\*[^*\n][^*\n]{0,78}\*\*:")
    CUSTOM_DELIMITER_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"(?<![\|])\s*::\s*|(?<!\|)\s*->\s*(?!\|)"
    )
    LIST_PATTERN: ClassVar[re.Pattern[str]] = re.compile(r"(?m)^\s*(?:[-*]|\d+\.)\s+")
    MULTI_HEADER_PATTERN: ClassVar[re.Pattern[str]] = re.compile(r"(?m)^\*\*[^*\n][^*\n]{0,78}\*\*:")
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

    # Verbose patterns that indicate conversational/verbose content
    VERBOSE_PATTERNS: ClassVar[list[str]] = [
        "you should",
        "i recommend",
        "please",
        "thank you",
        "let me know",
        "feel free",
        "i suggest",
        "you might want",
        "consider using",
        "it would be",
        "it's important to",
        "make sure",
        "remember",
        "note:",
        "important:",
    ]
    IMPERATIVE_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"^\*\*[^*\n][^*\n]{0,78}\*\*:\s*"
        r"(?:Use|Never|Always|Check|Follow|Avoid|Run|Keep|Prefer|Treat|Record|Verify|Fix|Delete|Remove|Commit|Push|Restart|Rebuild|File|Store|Apply|Stop|Set|Add)\b"
    )

    @classmethod
    def validate_content(
        cls,
        content: str,
        tier: str | None = None,
        *,
        bypass_compactness: bool = False,
    ) -> None:
        """
        Validate episode content for conciseness and declarative style.

        Args:
            content: Episode content to validate
            tier: Optional tier for exact header enforcement
            bypass_compactness: When true, skip the strict-Caveman gate. Other
                rules (header, atomic structure, custom delimiters, verbose
                patterns) still run. Used by the UI "Save anyway" override.

        Raises:
            EpisodeValidationError: If content fails validation (header, conversational, delimiters)
        """
        detected = []
        content_lower = content.lower()

        # Rule 1: Header format
        if tier and tier not in {"mandate", "guardrail", "reference"}:
            raise EpisodeValidationError(
                message=f"Unsupported memory tier {tier!r}.",
                detected_patterns=["Unsupported Tier"],
            )
        if not cls.ANY_HEADER_PATTERN.match(content):
            message = (
                "Episode must start with a bold topic header. "
                "Format: '**Topic**: Content...'. "
                "Example: '**Service Scripts**: Use ./scripts/rebuild.sh...'"
            )
            detected_patterns = ["Missing Header"]
            raise EpisodeValidationError(
                message=message,
                detected_patterns=detected_patterns,
            )

        if tier and not cls.IMPERATIVE_PATTERN.match(content):
            raise EpisodeValidationError(
                message="Episode must start with a direct imperative after the topic header.",
                detected_patterns=["Weak Imperative"],
            )

        if cls.LIST_PATTERN.search(content) or len(cls.MULTI_HEADER_PATTERN.findall(content)) > 1:
            raise EpisodeValidationError(
                message="Episode must express one atomic rule, not a list or multi-header block.",
                detected_patterns=["Non-Atomic Structure"],
            )

        # Rule 6: Conversational patterns
        for pattern in cls.VERBOSE_PATTERNS:
            if pattern in content_lower:
                detected.append(pattern)

        if detected:
            raise EpisodeValidationError(
                message=f"Episode content is too verbose. "
                f"Write declarative facts, not conversational advice. "
                f"Detected patterns: {', '.join(repr(p) for p in detected)}",
                detected_patterns=detected,
            )

        # Rule 5: Custom delimiters (:: or -> outside tables)
        if cls.CUSTOM_DELIMITER_PATTERN.search(content):
            raise EpisodeValidationError(
                message="Do not use custom delimiters like '::' or '->'. "
                "Use standard punctuation or tables.",
                detected_patterns=["Custom Delimiters"],
            )

        if not bypass_compactness:
            try:
                validate_compactness(content, kind="memory")
            except CompactnessValidationError as exc:
                raise EpisodeValidationError(
                    message="Episode failed strict Caveman gate. " + "; ".join(exc.errors),
                    detected_patterns=list(exc.errors),
                ) from exc

    @classmethod
    def validate_content_simple(
        cls,
        content: str,
        *,
        bypass_compactness: bool = False,
    ) -> str | None:
        """
        Lightweight validation for generated learnings.

        Returns error message if invalid, None if valid.
        Used by episode_creator_core for lightweight validation.

        bypass_compactness: When true, skip the strict-Caveman gate. Used by
        the UI "Save anyway" override.
        """
        content_lower = content.lower()
        detected = []

        if cls.CUSTOM_DELIMITER_PATTERN.search(content):
            return "Do not use custom delimiters like '::' or '->'. Use standard punctuation or tables."

        for pattern in cls.VERBOSE_PATTERNS:
            if pattern in content_lower:
                detected.append(pattern)

        if detected:
            return (
                "Content is too verbose. Write declarative facts, not conversational advice. "
                f"Detected patterns: {', '.join(repr(p) for p in detected)}"
            )
        if not bypass_compactness:
            try:
                validate_compactness(content, kind="memory")
            except CompactnessValidationError as exc:
                return "Episode failed strict Caveman gate. " + "; ".join(exc.errors)
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
