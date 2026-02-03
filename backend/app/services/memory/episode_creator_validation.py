"""Content validation utilities for episode creation."""

from __future__ import annotations

# Verbose patterns that indicate conversational/verbose content
VERBOSE_PATTERNS = [
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
    "remember",
    "make sure",
    "note:",
    "important:",
]


def validate_content(content: str) -> str | None:
    """
    Validate episode content for conciseness and declarative style.

    Returns error message if invalid, None if valid.
    """
    content_lower = content.lower()
    detected = []

    for pattern in VERBOSE_PATTERNS:
        if pattern in content_lower:
            detected.append(pattern)

    if detected:
        return (
            f"Content is too verbose. Write declarative facts, not conversational advice. "
            f"Detected patterns: {', '.join(repr(p) for p in detected)}"
        )

    return None
