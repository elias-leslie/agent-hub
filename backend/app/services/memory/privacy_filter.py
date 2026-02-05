from __future__ import annotations

import re

_PRIVATE_PATTERN = re.compile(
    r"<private>.*?</private>",
    re.DOTALL,
)

_MEMORY_PATTERN = re.compile(
    r"<memory>.*?</memory>",
    re.DOTALL,
)


def strip_private_tags(content: str) -> tuple[str, int]:
    stripped, count = _PRIVATE_PATTERN.subn("[REDACTED]", content)
    return stripped, count


def strip_memory_tags(content: str) -> tuple[str, int]:
    stripped, count = _MEMORY_PATTERN.subn("", content)
    return stripped, count


def apply_privacy_filter(content: str) -> tuple[str, dict[str, int]]:
    filtered, private_count = strip_private_tags(content)
    filtered, memory_count = strip_memory_tags(filtered)
    stats = {
        "private_tags_stripped": private_count,
        "memory_tags_stripped": memory_count,
    }
    return filtered, stats
