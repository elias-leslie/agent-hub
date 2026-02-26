"""Data models, patterns, and constants for citation and tag parsing."""

import re
from enum import StrEnum

from pydantic import BaseModel

# Regex pattern for citations: [M:8-char-hex], [G:8-char-hex], or [R:8-char-hex]
# The 8-char hex is the first 8 characters of the full UUID
CITATION_PATTERN = re.compile(r"\[([MGR]):([a-f0-9]{8})\]", re.IGNORECASE)

# New format: [[F:friction:sf.cli:error message unhelpful when flag is invalid]]
FEEDBACK_TAG_PATTERN = re.compile(
    r"\[\[F:(friction|idea|improvement|praise):([a-z][a-z0-9]*\.[a-z_]+):(.*?)\]\]",
    re.IGNORECASE,
)

# Legacy format: [F:friction:sf.cli] error message (newline-terminated)
FEEDBACK_TAG_PATTERN_LEGACY = re.compile(
    r"\[F:(friction|idea|improvement|praise):([a-z][a-z0-9]*\.[a-z_]+)\]\s*(.*?)(?:\n|$)",
    re.IGNORECASE,
)

# Format: [[S:completed:Implemented inline summary parsing]]
SUMMARY_TAG_PATTERN = re.compile(
    r"\[\[S:(completed|partial|failed):(.*?)\]\]",
    re.IGNORECASE,
)

VALID_FEEDBACK_TYPES = frozenset({"friction", "idea", "improvement", "praise"})
VALID_SUMMARY_OUTCOMES = frozenset({"completed", "partial", "failed"})


class CitationType(StrEnum):
    """Type of citation."""

    MANDATE = "M"
    GUARDRAIL = "G"
    REFERENCE = "R"


class Citation(BaseModel):
    """A parsed citation from LLM response."""

    type: CitationType
    uuid_prefix: str  # 8-char hex prefix of the full UUID


class ParseResult(BaseModel):
    """Result of parsing citations from a response."""

    citations: list[Citation]
    mandate_count: int = 0
    guardrail_count: int = 0
    reference_count: int = 0
    unique_uuids: list[str] = []


class FeedbackTag(BaseModel):
    """A parsed inline feedback tag from LLM response."""

    feedback_type: str  # friction, idea, improvement, praise
    component_id: str  # sf.cli, ah.memory, etc.
    description: str  # trailing text after the tag


class FeedbackParseResult(BaseModel):
    """Result of parsing feedback tags from a response."""

    tags: list[FeedbackTag]
    friction_count: int = 0
    praise_count: int = 0
    idea_count: int = 0
    improvement_count: int = 0


class SummaryTag(BaseModel):
    """A parsed inline summary tag from LLM response."""

    outcome: str  # completed, partial, failed
    description: str


class SummaryParseResult(BaseModel):
    """Result of parsing summary tags from a response."""

    tags: list[SummaryTag]
