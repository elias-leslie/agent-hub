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
    ]

    @classmethod
    def validate_content(cls, content: str) -> None:
        """
        Validate episode content for conciseness and declarative style.

        Rejects verbose, conversational content that indicates the agent
        is not writing correctly the first time.

        Args:
            content: Episode content to validate

        Raises:
            EpisodeValidationError: If content contains verbose patterns
        """
        detected = []
        content_lower = content.lower()

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
