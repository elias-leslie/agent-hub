"""Parser for progress narration tags emitted by agents during execution.

Agents emit [[P:type:content]] tags in their assistant messages for observability.
This module extracts those tags from text content.
"""

from __future__ import annotations

import re
from typing import NamedTuple

NARRATION_TAG_PATTERN = re.compile(
    r"\[\[P:(?P<tag_type>[a-z_]+):(?P<content>[^\]]+)\]\]"
)

VALID_TAG_TYPES = frozenset(
    {"started", "found", "modified", "tested", "confidence", "blocked", "decision"}
)


class NarrationTag(NamedTuple):
    """A single parsed narration tag."""

    tag_type: str
    content: str


def parse_narration_tags(text: str) -> list[NarrationTag]:
    """Extract all valid [[P:type:content]] tags from text.

    Returns a list of NarrationTag tuples. Ignores tags with unknown types.
    """
    if not text or "[[P:" not in text:
        return []

    tags: list[NarrationTag] = []
    for match in NARRATION_TAG_PATTERN.finditer(text):
        tag_type = match.group("tag_type")
        if tag_type in VALID_TAG_TYPES:
            tags.append(NarrationTag(tag_type=tag_type, content=match.group("content").strip()))
    return tags
