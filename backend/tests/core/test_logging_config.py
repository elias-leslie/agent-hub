"""LOG_LEVEL / LOG_LEVELS reach the root and named loggers in every process that calls configure_logging."""

from __future__ import annotations

import logging

import pytest

from app.core.logging_config import configure_logging, parse_levels


def test_overrides_parse_and_reject_typos() -> None:
    assert parse_levels(" app.llm=debug, httpx=WARNING ,") == {"app.llm": "DEBUG", "httpx": "WARNING"}
    assert parse_levels("") == {}
    for bad in ("app.llm", "=DEBUG", "app.llm=LOUD"):
        with pytest.raises(ValueError):
            parse_levels(bad)


def test_configure_applies_root_and_named_levels() -> None:
    root, named = logging.getLogger(), logging.getLogger("app.llm.test_probe")
    saved = (root.level, named.level)
    try:
        configure_logging("WARNING", "app.llm.test_probe=DEBUG")
        assert root.level == logging.WARNING and root.handlers
        assert named.isEnabledFor(logging.DEBUG) and not logging.getLogger("app.other").isEnabledFor(logging.INFO)
    finally:
        root.setLevel(saved[0])
        named.setLevel(saved[1])
