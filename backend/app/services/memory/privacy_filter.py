from __future__ import annotations

from app.services.secret_redaction import redact_secrets


def _strip_tagged(content: str, tag: str, replacement: str) -> tuple[str, int]:
    """Replace each ``<tag>...</tag>`` span (non-greedy, non-overlapping).

    A linear scan instead of ``<tag>.*?</tag>``: the regex rescans to the end
    of the input from every unclosed opening tag, which is quadratic on
    content with many opening tags and no closing tag.
    """
    opening = f"<{tag}>"
    closing = f"</{tag}>"
    parts: list[str] = []
    count = 0
    position = 0
    while True:
        start = content.find(opening, position)
        if start < 0:
            break
        end = content.find(closing, start + len(opening))
        if end < 0:
            break
        parts.append(content[position:start])
        parts.append(replacement)
        position = end + len(closing)
        count += 1
    if not count:
        return content, 0
    parts.append(content[position:])
    return "".join(parts), count


def strip_private_tags(content: str) -> tuple[str, int]:
    return _strip_tagged(content, "private", "[REDACTED]")


def strip_memory_tags(content: str) -> tuple[str, int]:
    return _strip_tagged(content, "memory", "")


def apply_privacy_filter(content: str) -> tuple[str, dict[str, int]]:
    filtered, private_count = strip_private_tags(content)
    filtered, memory_count = strip_memory_tags(filtered)
    filtered, secret_counts = redact_secrets(filtered)
    stats = {
        "private_tags_stripped": private_count,
        "memory_tags_stripped": memory_count,
        "secrets_redacted": sum(secret_counts.values()),
    }
    return filtered, stats
