"""One logging setup for the API and every worker process.

``LOG_LEVEL`` sets the root level. ``LOG_LEVELS`` overrides single loggers, comma separated, for example
``LOG_LEVELS=app.llm=DEBUG,httpx=WARNING`` to see per-request model timing and per-turn tool-loop timing
without turning the whole service up.
"""

from __future__ import annotations

import logging

FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


def parse_levels(spec: str) -> dict[str, str]:
    """``name=LEVEL`` pairs; a malformed or unknown entry raises so a typo is not silently ignored."""

    levels: dict[str, str] = {}
    for item in filter(None, (part.strip() for part in spec.split(","))):
        name, sep, level = item.partition("=")
        level = level.strip().upper()
        if not sep or not name.strip() or not isinstance(logging.getLevelName(level), int):
            raise ValueError(f"LOG_LEVELS entry {item!r} is not logger=LEVEL")
        levels[name.strip()] = level
    return levels


def configure_logging(level: str | None = None, levels: str | None = None) -> None:
    """Apply the root level and per-logger overrides; adds a stderr handler only when none is installed."""

    from app.config import settings

    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(FORMAT))
        root.addHandler(handler)
    root.setLevel((level or settings.log_level).upper())
    for name, value in parse_levels(levels if levels is not None else settings.log_levels).items():
        logging.getLogger(name).setLevel(value)
