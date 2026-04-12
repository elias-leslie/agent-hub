"""Tier-aware prompt rendering helpers for progressive memory context."""

from __future__ import annotations

import re
from collections import Counter

from .budget import count_tokens
from .context_profiles import (
    MemoryConsumerProfile,
    full_render_tags_for_profile,
    resolve_consumer_profile,
    summarize_policies_for_profile,
)
from .service import MemorySearchResult

PROMPT_TIER_L0 = "L0"
PROMPT_TIER_L1 = "L1"
PROMPT_TIER_L2 = "L2"

_QUERY_TOKEN_PATTERN = re.compile(r"[a-z0-9_./-]{3,}")
_L0_MAX_CHARS = 72
_L1_MAX_CHARS = 220
_FULL_TEXT_TOKEN_THRESHOLD = 24
_QUERY_MATCH_THRESHOLD = 3


def get_rendered_content(item: MemorySearchResult) -> str:
    """Return the currently selected prompt text for a memory item."""
    return item.prompt_content


def plan_context_render_tiers(
    mandates: list[MemorySearchResult],
    guardrails: list[MemorySearchResult],
    reference_index: list[MemorySearchResult],
    references: list[MemorySearchResult],
    query: str,
    consumer_profile: str | None = None,
) -> None:
    """Assign an initial render tier to each injected memory item."""
    query_terms = _tokenize(query)
    profile = resolve_consumer_profile(consumer_profile)
    force_full_tags = full_render_tags_for_profile(consumer_profile)
    for block, items in (
        ("mandate", mandates),
        ("guardrail", guardrails),
        ("reference_index", reference_index),
        ("reference", references),
    ):
        for item in items:
            tier, reason = _select_initial_tier(
                item,
                block=block,
                profile=profile,
                query_terms=query_terms,
                force_full_tags=force_full_tags,
            )
            _apply_render_tier(item, tier, reason)


def demote_item_to_fit_budget(item: MemorySearchResult) -> bool:
    """Demote a *reference* item one tier to reduce prompt footprint.

    Only applicable to references — mandates and guardrails are always L2.
    Returns True when changed.
    """
    current_tier = item.render_tier or PROMPT_TIER_L2
    if current_tier == PROMPT_TIER_L2:
        _apply_render_tier(item, PROMPT_TIER_L1, _budget_reason(item.render_reason))
        return True
    if current_tier == PROMPT_TIER_L1:
        _apply_render_tier(item, PROMPT_TIER_L0, _budget_reason(item.render_reason))
        return True
    return False


def build_memory_plan_debug(
    mandates: list[MemorySearchResult],
    guardrails: list[MemorySearchResult],
    reference_index: list[MemorySearchResult],
    references: list[MemorySearchResult],
) -> dict[str, object]:
    """Return compact debug metadata describing the final render plan."""
    plan: list[dict[str, object]] = []
    tier_counts: Counter[str] = Counter()
    render_chars = 0
    full_chars = 0

    for block, items in (
        ("mandate", mandates),
        ("guardrail", guardrails),
        ("reference_index", reference_index),
        ("reference", references),
    ):
        for item in items:
            rendered = get_rendered_content(item)
            full_tokens = count_tokens(item.content)
            rendered_tokens = count_tokens(rendered)
            tier = item.render_tier or PROMPT_TIER_L2
            tier_counts[tier] += 1
            render_chars += len(rendered)
            full_chars += len(item.content)
            plan.append(
                {
                    "uuid": item.uuid,
                    "block": block,
                    "tier": tier,
                    "reason": item.render_reason,
                    "summary": item.summary,
                    "full_tokens": full_tokens,
                    "rendered_tokens": rendered_tokens,
                }
            )

    return {
        "tier_counts": dict(sorted(tier_counts.items())),
        "render_chars": render_chars,
        "full_chars": full_chars,
        "render_chars_saved": max(0, full_chars - render_chars),
        "memory_plan": plan,
    }


def _select_initial_tier(
    item: MemorySearchResult,
    *,
    block: str,
    profile: MemoryConsumerProfile,
    query_terms: set[str],
    force_full_tags: set[str],
) -> tuple[str, str]:
    if force_full_tags and force_full_tags.intersection(item.tags):
        return PROMPT_TIER_L2, "consumer_profile_tag"

    # Mandates and guardrails are instructions — always full text.
    # Token budget is managed by episode count (target: 25-30 mandates),
    # not by compressing instructions into useless summaries.
    if block == "mandate":
        if summarize_policies_for_profile(profile.value):
            return PROMPT_TIER_L0, "startup_policy_summary"
        return PROMPT_TIER_L2, "mandate"

    if block == "guardrail":
        if summarize_policies_for_profile(profile.value):
            return PROMPT_TIER_L0, "startup_policy_summary"
        return PROMPT_TIER_L2, "guardrail"

    if block == "reference_index":
        return PROMPT_TIER_L0, "reference_index"

    # References use progressive disclosure (query-dependent tiers).
    query_overlap = _query_overlap(item, query_terms)
    if count_tokens(item.content) <= _FULL_TEXT_TOKEN_THRESHOLD:
        return PROMPT_TIER_L2, "already_compact"
    if query_overlap >= _QUERY_MATCH_THRESHOLD:
        return PROMPT_TIER_L2, "query_match"
    return PROMPT_TIER_L1, "selected_reference"


def _apply_render_tier(item: MemorySearchResult, tier: str, reason: str | None) -> None:
    item.render_tier = tier
    item.overview = item.overview or _build_overview(item.content)
    item.render_reason = reason
    if tier == PROMPT_TIER_L0:
        item.rendered_content = _build_summary(item)
    elif tier == PROMPT_TIER_L1:
        item.rendered_content = item.overview
    else:
        item.rendered_content = item.content


def _build_summary(item: MemorySearchResult) -> str:
    if item.summary:
        return _collapse_whitespace(item.summary)
    return _truncate_sentence(item.content, _L0_MAX_CHARS)


def _build_overview(content: str) -> str:
    return _truncate_sentence(content, _L1_MAX_CHARS)


def _truncate_sentence(text: str, max_chars: int) -> str:
    clean = _collapse_whitespace(text)
    if len(clean) <= max_chars:
        return clean

    sentence_end = clean.rfind(". ", 0, max_chars)
    if sentence_end >= max_chars // 2:
        return clean[: sentence_end + 1]

    word_end = clean.rfind(" ", 0, max_chars - 3)
    if word_end <= 0:
        return clean[: max_chars - 3] + "..."
    return clean[:word_end] + "..."


def _collapse_whitespace(text: str) -> str:
    return " ".join(text.split())


def _tokenize(text: str) -> set[str]:
    return {match.group(0) for match in _QUERY_TOKEN_PATTERN.finditer(text.lower())}


def _query_overlap(item: MemorySearchResult, query_terms: set[str]) -> int:
    if not query_terms:
        return 0
    haystack_terms = _tokenize(
        " ".join(
            [
                item.summary or "",
                item.overview or "",
                " ".join(item.tags),
            ]
        )
    )
    return len(query_terms & haystack_terms)


def _budget_reason(reason: str | None) -> str:
    if not reason:
        return "budget_demoted"
    if "budget_demoted" in reason:
        return reason
    return f"{reason}+budget_demoted"
