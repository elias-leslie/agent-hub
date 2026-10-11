"""Agent-only context style warnings (owner directive 2026-10-11)."""
from __future__ import annotations

from app.services.context_review import deterministic_findings
from app.services.context_style import AUTHORING_HINT, style_warnings


def test_terse_content_has_no_warnings() -> None:
    assert style_warnings("Run st check --quick before commit. Never print .env.") == []
    assert style_warnings("") == []


def test_padding_phrases_warn_with_hint() -> None:
    warnings = style_warnings("Please make sure to run the tests in order to verify.")
    assert warnings[0] == "padding: in order to, make sure to, please"
    assert warnings[-1] == AUTHORING_HINT


def test_token_growth_warns_only_when_large() -> None:
    base = "Run st check before commit."
    assert style_warnings(base + " Use --changed-only.", base) == []
    grown = base + " Extra explanatory sentence about the reasons." * 10
    assert any(w.startswith("token growth: ") for w in style_warnings(grown, base))


def test_review_flags_padding_with_verbatim_passage() -> None:
    sources = [{"source_id": "p1", "content": "Note that you should please rebuild.", "policy": None}]
    findings = deterministic_findings(sources)
    assert [(f["kind"], f["passages"]) for f in findings] == [("unnecessary", {"p1": "Note that"})]
    assert deterministic_findings([{"source_id": "p2", "content": "Rebuild after edits.", "policy": None}]) == []
