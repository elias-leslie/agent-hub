"""Episode validation utilities."""

from typing import ClassVar


class EpisodeValidationError(Exception):
    """Raised when episode content fails validation."""

    def __init__(self, message: str, detected_patterns: list[str]):
        self.message = message
        self.detected_patterns = detected_patterns
        super().__init__(message)


class EpisodeValidator:
    """Validates episode content for quality and conciseness."""

    # Verbose patterns that indicate conversational/verbose content
    # Validation patterns
    import re

    HEADER_PATTERN: ClassVar[re.Pattern] = re.compile(r"^\*\*[^*]+\*\*:")
    CUSTOM_DELIMITER_PATTERN: ClassVar[re.Pattern] = re.compile(
        r"(?<![\|])\s*::\s*|(?<!\|)\s*->\s*(?!\|)"
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

    @classmethod
    def validate_content(cls, content: str) -> None:
        """
        Validate episode content for conciseness and declarative style.

        Args:
            content: Episode content to validate

        Raises:
            EpisodeValidationError: If content fails validation (header, conversational, delimiters)
        """
        detected = []
        content_lower = content.lower()

        # Rule 1: Header format (**Topic**: ...)
        if not cls.HEADER_PATTERN.match(content):
            raise EpisodeValidationError(
                message="Episode must start with a bold topic header. "
                "Format: '**Topic**: Content...'. "
                "Example: '**Service Scripts**: Use ./scripts/rebuild.sh...'",
                detected_patterns=["Missing Header"],
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

        if len(summary) > 50:
            raise EpisodeValidationError(
                message=f"Summary is too long ({len(summary)} chars). "
                "Keep it under 50 characters for the index.",
                detected_patterns=["Summary Too Long"],
            )
