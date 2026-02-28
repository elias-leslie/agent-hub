"""Constants for the persona API."""

from __future__ import annotations

# Mapping of user-facing time-range labels to hours (0 = no filter)
HOURS_MAP: dict[str, int] = {
    "6h": 6,
    "24h": 24,
    "7d": 168,
    "30d": 720,
    "all": 0,
}

# Fields that receive shrinkage-protection checks on update
PROTECTED_TEXT_FIELDS: tuple[str, ...] = (
    "user_context",
    "personality",
    "heartbeat_instructions",
)

# Minimum existing length before shrinkage protection kicks in
SHRINKAGE_MIN_LEN: int = 200

# Fraction below which a new value is considered suspicious data loss
SHRINKAGE_RATIO: float = 0.5

# Projects included in the persona activity timeline
PERSONA_PROJECTS: tuple[str, ...] = ("persona-sandbox", "summitflow")

# Maximum number of event previews fetched per session
EVENT_PREVIEW_LIMIT: int = 3

# Maximum character length for content previews
CONTENT_PREVIEW_LEN: int = 200
