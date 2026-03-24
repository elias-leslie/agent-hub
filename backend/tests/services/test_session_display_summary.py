"""Tests for rich session display summary selection."""

from __future__ import annotations

from app.services.session_display_summary import (
    clean_display_summary_text,
    extract_outcome_summary,
    select_display_summary,
)


def test_select_display_summary_prefers_latest_summary_tag() -> None:
    result = select_display_summary(
        [
            "HEARTBEAT_ACTION Reviewed queue state. [[S:completed:Reviewed queue, cleanup, git, and session truth; dispatched the highest-value fixes.]]",
            "Older assistant output.",
        ],
        summary_oneliner="Reviewed queue, cleanup, git, and session truth; dispatched the highest-value fi...",
    )

    assert result == "Reviewed queue, cleanup, git, and session truth; dispatched the highest-value fixes."


def test_select_display_summary_falls_back_to_narration_aware_assistant_text() -> None:
    result = select_display_summary(
        [
            "[[P:started:checking queue]] HEARTBEAT_ACTION Reconciled stale session residue and queued the repair lane.",
        ],
        summary_oneliner="Stale truncated summary...",
    )

    assert result == "checking queue Reconciled stale session residue and queued the repair lane."


def test_select_display_summary_uses_cleaned_summary_oneliner_when_messages_are_noise() -> None:
    result = select_display_summary(
        ["session started"],
        summary_oneliner="[[P:started:checking]] Applied: [M:1234abcd] Useful fallback summary",
    )

    assert result == "Useful fallback summary"


def test_clean_display_summary_text_removes_empty_fragments() -> None:
    assert clean_display_summary_text("[[P:started:test]] Applied: [M:1234abcd]") is None


def test_select_display_summary_uses_narration_tags_before_answer_only_fallback() -> None:
    result = select_display_summary(
        [
            (
                "[[P:started:looking up Cloudflare Markdown for Agents definition via official web sources]]"
                "[[P:found:official Cloudflare docs page for Markdown for Agents]]"
                "Cloudflare Markdown for Agents is a feature that serves HTML as Markdown."
            ),
        ],
        summary_oneliner="Cloudflare Markdown for Agents is a feature that serves HTML as Markdown.",
    )

    assert result == (
        "looking up Cloudflare Markdown for Agents definition via official web sources "
        "official Cloudflare docs page for Markdown for Agents "
        "Cloudflare Markdown for Agents is a feature that serves HTML as Markdown."
    )


def test_extract_outcome_summary_skips_procedural_commit_instruction() -> None:
    content = (
        "[[P:tested:dt -q -d passes clean - biome OK, tsc OK, zero errors]]"
        "[[P:confidence:95:RoundManager.ts = 200 lines (from 435), 3 functions, tsc+biome clean. Ready to commit.]]"
        "Type checks pass. Now commit via `/commit_it`."
    )

    result = extract_outcome_summary(content)

    assert result is not None
    assert "/commit_it" not in result
    assert (
        "passes clean" in result
        or "tsc+biome clean" in result
        or "Type checks pass." in result
    )


def test_select_display_summary_prefers_outcome_over_raw_command_tail() -> None:
    result = select_display_summary(
        [
            (
                "[[P:tested:dt -q -d passes clean - biome OK, tsc OK, zero errors]]"
                "[[P:confidence:95:RoundManager.ts = 200 lines (from 435), 3 functions, tsc+biome clean. Ready to commit.]]"
                "Type checks pass. Now commit via `/commit_it`."
            ),
        ],
        summary_oneliner="[[P:tested:dt -q -d passes clean - biome OK, tsc OK, zero errors]] Type checks pass. Now commit via `/commit_it`.",
    )

    assert result is not None
    assert "/commit_it" not in result
    assert "passes clean" in result or "Type checks pass." in result
