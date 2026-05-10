"""Tests for per-memory render_mode and per-profile tier_override.

Covers the user-facing render-expansion controls:
- Memory.render_mode forces L0/L1/L2 across all profiles when set.
- RuntimeContextOverride.tier_override beats render_mode when set.
- The codex_startup_full tag still works as a fallback when neither is set.
- Auto behavior is preserved when both are unset.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.services.memory.context_builder_tiers import (
    PROMPT_TIER_L0,
    PROMPT_TIER_L1,
    PROMPT_TIER_L2,
    RENDER_MODE_TO_TIER,
    apply_render_tier,
    plan_context_render_tiers,
)
from app.services.memory.context_profiles import (
    CODEX_STARTUP_FULL_TAG,
    MemoryConsumerProfile,
)
from app.services.memory.service import MemorySearchResult, MemorySource
from app.services.runtime_context import RuntimeContextOverridePayload, _resolve_overrides


def _make_item(
    *,
    uuid: str = "item-1",
    content: str = "x" * 600,
    tags: list[str] | None = None,
    render_mode: str | None = None,
    summary: str | None = None,
) -> MemorySearchResult:
    return MemorySearchResult(
        uuid=uuid,
        content=content,
        summary=summary,
        source=MemorySource.SYSTEM,
        relevance_score=1.0,
        created_at=datetime.now(UTC),
        facts=[],
        tags=tags or [],
        render_mode=render_mode,
    )


class TestRenderModeMap:
    """Sanity check that render_mode strings map to the right tier."""

    def test_render_mode_to_tier_map(self) -> None:
        assert RENDER_MODE_TO_TIER["full"] == PROMPT_TIER_L2
        assert RENDER_MODE_TO_TIER["compact"] == PROMPT_TIER_L1
        assert RENDER_MODE_TO_TIER["summary"] == PROMPT_TIER_L0


class TestRenderModeOverridesAutoTier:
    """Per-memory render_mode wins over the auto/profile-driven tier rules."""

    def test_full_forces_L2_on_a_reference_that_would_be_L1(self) -> None:
        # Long reference content with no query overlap → would default to L1.
        item = _make_item(render_mode="full")
        plan_context_render_tiers(
            mandates=[],
            guardrails=[],
            reference_index=[],
            references=[item],
            query="unrelated",
            consumer_profile=MemoryConsumerProfile.AGENT_RUNTIME.value,
        )
        assert item.render_tier == PROMPT_TIER_L2
        assert item.render_reason == "memory_render_mode"
        assert item.rendered_content == item.content

    def test_summary_forces_L0_on_a_mandate(self) -> None:
        # agent_runtime profile would normally render mandates at L2.
        item = _make_item(render_mode="summary", summary="be terse")
        plan_context_render_tiers(
            mandates=[item],
            guardrails=[],
            reference_index=[],
            references=[],
            query="",
            consumer_profile=MemoryConsumerProfile.AGENT_RUNTIME.value,
        )
        assert item.render_tier == PROMPT_TIER_L0
        assert item.render_reason == "memory_render_mode"
        assert item.rendered_content == "be terse"

    def test_compact_forces_L1_on_a_mandate(self) -> None:
        item = _make_item(render_mode="compact")
        plan_context_render_tiers(
            mandates=[item],
            guardrails=[],
            reference_index=[],
            references=[],
            query="",
            consumer_profile=MemoryConsumerProfile.AGENT_RUNTIME.value,
        )
        assert item.render_tier == PROMPT_TIER_L1
        assert item.render_reason == "memory_render_mode"

    def test_unknown_render_mode_falls_through_to_auto(self) -> None:
        # Defense in depth: a stray value in the DB should not crash; auto rules apply.
        item = _make_item(render_mode="bogus")
        plan_context_render_tiers(
            mandates=[item],
            guardrails=[],
            reference_index=[],
            references=[],
            query="",
            consumer_profile=MemoryConsumerProfile.AGENT_RUNTIME.value,
        )
        assert item.render_tier == PROMPT_TIER_L2
        assert item.render_reason == "mandate"


class TestAutoBehaviorPreserved:
    """When render_mode is unset, the existing tier rules must remain unchanged."""

    def test_no_render_mode_mandate_stays_L2_on_agent_runtime(self) -> None:
        item = _make_item()
        plan_context_render_tiers(
            mandates=[item],
            guardrails=[],
            reference_index=[],
            references=[],
            query="",
            consumer_profile=MemoryConsumerProfile.AGENT_RUNTIME.value,
        )
        assert item.render_tier == PROMPT_TIER_L2
        assert item.render_reason == "mandate"

    def test_no_render_mode_mandate_summarizes_under_codex_startup(self) -> None:
        item = _make_item(summary="rule-1")
        plan_context_render_tiers(
            mandates=[item],
            guardrails=[],
            reference_index=[],
            references=[],
            query="",
            consumer_profile=MemoryConsumerProfile.AGENT_STARTUP.value,
        )
        assert item.render_tier == PROMPT_TIER_L0
        assert item.render_reason == "policy_summary"

    def test_codex_startup_full_tag_still_forces_L2_when_no_render_mode(self) -> None:
        item = _make_item(tags=[CODEX_STARTUP_FULL_TAG])
        plan_context_render_tiers(
            mandates=[item],
            guardrails=[],
            reference_index=[],
            references=[],
            query="",
            consumer_profile=MemoryConsumerProfile.AGENT_STARTUP.value,
        )
        assert item.render_tier == PROMPT_TIER_L2
        assert item.render_reason == "consumer_profile_tag"

    def test_render_mode_beats_codex_startup_full_tag(self) -> None:
        item = _make_item(tags=[CODEX_STARTUP_FULL_TAG], render_mode="summary")
        plan_context_render_tiers(
            mandates=[item],
            guardrails=[],
            reference_index=[],
            references=[],
            query="",
            consumer_profile=MemoryConsumerProfile.AGENT_STARTUP.value,
        )
        assert item.render_tier == PROMPT_TIER_L0
        assert item.render_reason == "memory_render_mode"


class TestTierOverrideSchema:
    """Pydantic validation for RuntimeContextOverridePayload.tier_override."""

    def test_accepts_valid_tier_override(self) -> None:
        payload = RuntimeContextOverridePayload(
            source_type="memory",
            source_id="memory-1",
            tier_override="L0",
        )
        assert payload.tier_override == "L0"

    def test_defaults_to_none(self) -> None:
        payload = RuntimeContextOverridePayload(
            source_type="memory",
            source_id="memory-1",
        )
        assert payload.tier_override is None

    @pytest.mark.parametrize("bogus", ["L3", "l0", "full", ""])
    def test_rejects_invalid_tier_override(self, bogus: str) -> None:
        with pytest.raises(ValidationError):
            RuntimeContextOverridePayload(
                source_type="memory",
                source_id="memory-1",
                tier_override=bogus,
            )


class TestTierOverrideBeatsRenderMode:
    """A per-profile runtime override on the same memory wins over render_mode."""

    def test_apply_render_tier_user_override_overrides_memory_render_mode(self) -> None:
        # First simulate the auto/render_mode pass.
        item = _make_item(render_mode="full")
        plan_context_render_tiers(
            mandates=[],
            guardrails=[],
            reference_index=[],
            references=[item],
            query="",
            consumer_profile=MemoryConsumerProfile.AGENT_RUNTIME.value,
        )
        assert item.render_tier == PROMPT_TIER_L2

        # Then simulate the runtime-override pass — equivalent to what
        # apply_tier_overrides_to_context does for a tier_override="L0" row.
        apply_render_tier(item, "L0", "user_override")
        assert item.render_tier == PROMPT_TIER_L0
        assert item.render_reason == "user_override"

    def test_resolved_overrides_preserves_tier_override_field(self) -> None:
        rows = [
            SimpleNamespace(
                id="override-1",
                consumer_profile="codex_startup",
                project_id=None,
                source_type="memory",
                source_id="memory-1",
                mode="order",
                position=50,
                enabled=True,
                note=None,
                tier_override="L1",
            ),
        ]
        resolved = _resolve_overrides(rows)
        assert len(resolved) == 1
        assert resolved[0].tier_override == "L1"
