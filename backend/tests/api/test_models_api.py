"""Tests for model catalog API helpers."""

from datetime import UTC, datetime
from types import SimpleNamespace

from app.api.models import _build_catalog_health, _build_model_info
from app.constants.catalog import get_model_entry
from app.constants.catalog_types import ModelCapabilities, ModelCost, ModelEntry, ModelScores
from app.models.model_enrichment import ModelEnrichment


def test_build_model_info_includes_extended_capabilities() -> None:
    entry = get_model_entry("codex/gpt-6.1-sol")
    assert entry is not None

    info = _build_model_info(entry)

    assert info.capabilities.has_thinking is True
    assert info.capabilities.supports_tool_execution is True
    assert info.capabilities.supports_verbosity is True
    assert info.capabilities.supports_xhigh is True
    assert info.capabilities.supports_session_cache is True


def test_get_model_entry_resolves_the_claude_opus_alias() -> None:
    entry = get_model_entry("opus")
    assert entry is not None

    info = _build_model_info(entry)

    assert info.id == "claude-opus-5-5"
    assert info.name == "Claude Opus 5.5"
    assert info.capabilities.has_vision is True
    # The Claude Code CLI route runs tool-denied.
    assert info.capabilities.supports_tool_execution is False
    assert info.cost.input_per_m == 4.0
    assert info.cost.output_per_m == 20.0


def test_gemini_flash_lite_models_support_agentic_extraction() -> None:
    for model_id, expected_cost in [
        ("gemini-3.1-flash-lite", (0.25, 1.5)),
        ("gemini-2.5-flash-lite", (0.1, 0.4)),
    ]:
        entry = get_model_entry(model_id)
        assert entry is not None

        info = _build_model_info(entry)

        assert info.capabilities.has_vision is True
        assert info.capabilities.has_thinking is True
        assert info.capabilities.supports_pdf is True
        assert info.capabilities.supports_audio is True
        assert info.capabilities.supports_tool_execution is True
        assert info.capabilities.max_output_tokens == 65536
        assert info.cost.input_per_m == expected_cost[0]
        assert info.cost.output_per_m == expected_cost[1]
        assert info.availability is not None
        assert "free_tier" in info.availability


def test_gemini_3_5_flash_supports_long_form_audio_review() -> None:
    entry = get_model_entry("gemini-3.5-flash")
    assert entry is not None

    info = _build_model_info(entry)

    assert info.provider == "gemini"
    assert info.capabilities.supports_audio is True
    assert info.capabilities.has_thinking is True
    assert info.capabilities.max_output_tokens == 65_536
    assert info.context_window == 1_048_576
    assert info.cost.input_per_m == 1.5
    assert info.cost.output_per_m == 9.0
    assert info.availability is not None
    assert "stable" in info.availability


def test_gemini_free_tier_catalog_includes_current_generation_models() -> None:
    for model_id in [
        "gemini-3.8-flash",
        "gemini-3.7-flash",
        "gemini-3.6-flash",
        "gemini-3.5-flash",
        "gemini-3.1-flash-lite",
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
    ]:
        entry = get_model_entry(model_id)
        assert entry is not None

        info = _build_model_info(entry)

        assert info.provider == "gemini"
        assert info.capabilities.supports_tool_execution is True
        assert info.capabilities.has_thinking is True
        assert info.availability is not None
        assert "free_tier" in info.availability


def test_get_model_entry_returns_none_for_unknown_model() -> None:
    # Arrange
    unknown_id = "unknown/does-not-exist"

    # Act
    entry = get_model_entry(unknown_id)

    # Assert
    assert entry is None


def test_build_model_info_partial_capabilities() -> None:
    # Arrange — entry with only has_vision and supports_pdf set; all others default to False
    entry = ModelEntry(
        id="test/partial-caps",
        alias="partial-caps",
        name="Partial Caps Model",
        hint="test model with partial capabilities",
        provider="test",
        scores=ModelScores(coding=50, reasoning=50, planning=50, tool_use=50, instruction=50, design=50),
        cost=ModelCost(input_per_m=1.0, output_per_m=2.0),
        context_window=8192,
        speed_tier="medium",
        capabilities=ModelCapabilities(has_vision=True, supports_pdf=True),
    )

    # Act
    info = _build_model_info(entry)

    # Assert — only the two explicitly set flags are True; the rest remain False
    assert info.capabilities.has_vision is True
    assert info.capabilities.supports_pdf is True
    assert info.capabilities.can_generate_images is False
    assert info.capabilities.can_edit_images is False
    assert info.capabilities.has_thinking is False
    assert info.capabilities.supports_audio is False
    assert info.capabilities.supports_tool_execution is False
    assert info.capabilities.supports_verbosity is False
    assert info.capabilities.supports_xhigh is False
    assert info.capabilities.supports_session_cache is False


def test_build_model_info_prefers_enrichment_cost_and_speed() -> None:
    entry = ModelEntry(
        id="test/enriched-cost",
        alias="enriched-cost",
        name="Enriched Cost Model",
        hint="test model with price overlay",
        provider="test",
        scores=ModelScores(coding=50, reasoning=50, planning=50, tool_use=50, instruction=50, design=50),
        cost=ModelCost(input_per_m=3.0, output_per_m=15.0),
        context_window=8192,
        speed_tier="slow",
        capabilities=ModelCapabilities(),
    )
    enrichment = ModelEnrichment(
        model_id=entry.id,
        ext_speed_tier="fast",
        ext_input_per_m=2.0,
        ext_output_per_m=6.0,
        synced_at=datetime.now(UTC),
    )

    info = _build_model_info(entry, enrichment)

    assert info.cost.input_per_m == 2.0
    assert info.cost.output_per_m == 6.0
    assert info.cost.source == "enrichment"
    assert info.speed_tier == "fast"


def test_build_model_info_preserves_per_image_pricing() -> None:
    entry = ModelEntry(
        id="test/per-image",
        alias="per-image",
        name="Per Image Model",
        hint="image unit pricing",
        provider="test",
        scores=ModelScores(coding=0, reasoning=0, planning=0, tool_use=0, instruction=50, design=80),
        cost=ModelCost(input_per_m=0.0, output_per_m=0.0, pricing_unit="per_image", unit_price=0.07),
        context_window=0,
        speed_tier="fast",
        capabilities=ModelCapabilities(can_generate_images=True, max_output_tokens=0),
    )

    info = _build_model_info(entry)

    assert info.cost.pricing_unit == "per_image"
    assert info.cost.unit_price == 0.07
    assert info.cost.source == "catalog"


def test_build_catalog_health_reads_sync_state_discovery() -> None:
    entry = get_model_entry("xai/grok-4.20-0309-reasoning")
    assert entry is not None

    enrichment = ModelEnrichment(
        model_id=entry.id,
        ext_input_per_m=2.0,
        ext_output_per_m=6.0,
        synced_at=datetime.now(UTC),
    )
    sync_state = SimpleNamespace(
        status="success",
        error=None,
        source_counts={"models_dev": 10, "benchmarks": 5, "bfcl": 2, "livebench": 3},
        discovery_summary={
            "unmatched_model_count": 4,
            "unmatched_provider_count": 1,
            "top_providers": [
                {
                    "provider_id": "x-ai",
                    "provider_name": "xAI",
                    "unmatched_count": 4,
                    "sample_model_ids": ["grok-4.1", "grok-4.2"],
                }
            ],
            "sample_model_ids": ["grok-4.1", "grok-4.2"],
        },
    )

    health = _build_catalog_health(
        entries=[entry],
        enrichments={entry.id: enrichment},
        sync_state=sync_state,
        last_sync=datetime.now(UTC),
    )

    assert health.sync_status == "success"
    assert health.models_with_live_pricing >= 1
    assert health.discovery is not None
    assert health.discovery.unmatched_model_count == 4
    assert health.discovery.top_providers[0].provider_name == "xAI"


def _watchlist_state() -> SimpleNamespace:
    return SimpleNamespace(
        status="success",
        error=None,
        source_counts={"models_dev": 10},
        discovery_summary={
            "unmatched_model_count": 3,
            "unmatched_provider_count": 2,
            "top_providers": [
                {"provider_id": "claude", "provider_name": "Claude", "unmatched_count": 1,
                 "sample_model_ids": ["claude-opus-5-5"]},
                {"provider_id": "gemini", "provider_name": "Gemini", "unmatched_count": 2,
                 "sample_model_ids": ["gemini-9-pro", "claude-fable-5-1"]},
            ],
            "sample_model_ids": ["claude-opus-5-5", "gemini-9-pro", "claude-fable-5-1"],
        },
    )


def test_watchlist_drops_models_catalogued_or_retired_after_the_saved_sync() -> None:
    entry = get_model_entry("xai/grok-4.20-0309-reasoning")
    assert entry is not None

    health = _build_catalog_health(
        entries=[entry],
        enrichments={},
        sync_state=_watchlist_state(),
        last_sync=datetime.now(UTC),
        known_ids={"claude-opus-5-5", "claude-fable-5-1", "grok-4.20-0309-reasoning"},
    )

    assert health.discovery is not None
    assert health.discovery.sample_model_ids == ["gemini-9-pro"]
    assert [p.provider_id for p in health.discovery.top_providers] == ["gemini"]
    assert health.discovery.top_providers[0].unmatched_count == 1
    assert (health.discovery.unmatched_model_count, health.discovery.unmatched_provider_count) == (1, 1)


def test_subscription_and_local_models_are_not_counted_as_missing_live_pricing() -> None:
    metered = get_model_entry("xai/grok-4.20-0309-reasoning")
    assert metered is not None
    subscription = _entry_with(metered, id="claude-opus-5-5", provider="claude",
                               availability="claude_code_cli_subscription")
    local = _entry_with(metered, id="local/qwen", provider="local", availability=None)

    health = _build_catalog_health(
        entries=[metered, subscription, local], enrichments={}, sync_state=None, last_sync=None,
    )

    assert (health.models_with_live_pricing, health.models_missing_live_pricing) == (0, 1)


def _entry_with(entry: ModelEntry, **changes) -> ModelEntry:
    from dataclasses import replace

    return replace(entry, **changes)
