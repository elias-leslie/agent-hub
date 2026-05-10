"""Tests for the DB-backed compactness policy and analyze_compactness honoring it."""

from __future__ import annotations

import pytest

from app.services import compactness_policy
from app.services.compactness import analyze_compactness
from app.services.compactness_policy import CompactnessPolicyValues


@pytest.fixture(autouse=True)
def _reset_cache():
    compactness_policy.invalidate_cache()
    yield
    compactness_policy.invalidate_cache()


def test_get_policy_falls_back_to_defaults_when_unhydrated():
    assert compactness_policy.get_policy() == compactness_policy.DEFAULTS


def test_analyze_compactness_uses_default_memory_chars_warning():
    long_content = "**Topic**: Use " + ("alpha " * 60)
    report = analyze_compactness(long_content, kind="memory")
    assert any("long memory" in warning for warning in report.warnings)


def test_analyze_compactness_respects_overridden_memory_chars():
    compactness_policy._set_cache(
        CompactnessPolicyValues(memory_max_chars=10_000)
    )
    long_content = "**Topic**: Use " + ("alpha " * 60)
    report = analyze_compactness(long_content, kind="memory")
    assert not any("long memory" in warning for warning in report.warnings)


def test_analyze_compactness_respects_overridden_sentence_words():
    compactness_policy._set_cache(
        CompactnessPolicyValues(max_sentence_words=4)
    )
    content = "**Topic**: Use the standard runbook entry today."
    report = analyze_compactness(content, kind="memory")
    assert any("long prose sentences" in error for error in report.errors)


def test_invalidate_cache_drops_overrides():
    compactness_policy._set_cache(
        CompactnessPolicyValues(memory_max_chars=10)
    )
    compactness_policy.invalidate_cache()
    assert compactness_policy.get_policy() == compactness_policy.DEFAULTS
