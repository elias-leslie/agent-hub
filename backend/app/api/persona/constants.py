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
)

# PERSONA_PROJECTS removed — persona activity now queries all projects
# from the project_permissions table (any tier != 'off').
# See activity.py _build_session_query() for the dynamic filter.

# Maximum number of event previews fetched per session
EVENT_PREVIEW_LIMIT: int = 3

# Maximum character length for content previews
CONTENT_PREVIEW_LEN: int = 200
