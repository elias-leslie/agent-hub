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


def test_memory_content_update_recomputes_token_count_and_fingerprint() -> None:
    from app.services.memory._repo_crud import _normalize_update_kwargs
    from app.services.memory.budget import count_tokens
    from app.services.memory.fingerprint import content_fingerprint

    content = "Run st check before commit."
    kwargs = _normalize_update_kwargs({"content": content, "token_count": 999})
    assert kwargs["token_count"] == count_tokens(content)
    assert kwargs["content_fingerprint"] == content_fingerprint(content)
    assert "token_count" not in _normalize_update_kwargs({"injection_tier": "reference"})


def test_memory_command_howto_warns_once_two_flagged_commands_appear() -> None:
    from app.services.context_style import memory_style_warnings

    howto = ("Default gh token 403s. Run `nightshift elevate request github-admin --reason '<why>' --wait`, "
             "then `nightshift elevate run github-admin -- gh ...`; `nightshift elevate status`.")
    warnings = memory_style_warnings(howto)
    assert warnings[0].startswith("tool how-to (2 commands): register an ST surface")
    assert memory_style_warnings("Use `st check --quick`, not raw pytest; `pyproject.toml` owns config.") == []
    assert style_warnings(howto) == []  # prompts keep the shared style check only


def test_command_detection_uses_tokens_and_stays_fast_on_long_spans() -> None:
    from app.services.context_style import _looks_like_command

    assert _looks_like_command("st check --quick")
    assert _looks_like_command("gh pr view -w")
    assert _looks_like_command("git diff -- path")
    assert not _looks_like_command("pyproject.toml")
    assert not _looks_like_command("Run --quick")  # head must be lowercase
    assert not _looks_like_command("st ---x -1")
    assert not _looks_like_command("a" * 50_000 + " b")  # CodeQL py/polynomial-redos input shape
