"""Tests for compact memory analytics lookback parsing."""

from datetime import timedelta

import pytest

from app.api.memory_lookback import parse_memory_lookback


def test_parse_memory_lookback_defaults_to_days() -> None:
    delta, label = parse_memory_lookback(None, fallback_days=30)

    assert delta == timedelta(days=30)
    assert label == "30d"


@pytest.mark.parametrize(
    ("lookback", "expected"),
    [
        ("1h", timedelta(hours=1)),
        ("1d", timedelta(days=1)),
        ("7d", timedelta(days=7)),
        ("14d", timedelta(days=14)),
        ("30d", timedelta(days=30)),
    ],
)
def test_parse_memory_lookback_accepts_supported_ranges(
    lookback: str,
    expected: timedelta,
) -> None:
    delta, label = parse_memory_lookback(lookback, fallback_days=30)

    assert delta == expected
    assert label == lookback


def test_parse_memory_lookback_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="Invalid lookback value"):
        parse_memory_lookback("2h", fallback_days=30)


def test_parse_memory_lookback_rejects_values_above_window_cap() -> None:
    with pytest.raises(ValueError, match="Invalid lookback value"):
        parse_memory_lookback("91d", fallback_days=30)
