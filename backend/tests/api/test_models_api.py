"""Tests for model catalog API helpers."""

from app.api.models import _build_model_info
from app.constants.catalog import get_model_entry
from app.constants.catalog_types import ModelCapabilities, ModelCost, ModelEntry, ModelScores


def test_build_model_info_includes_extended_capabilities() -> None:
    entry = get_model_entry("codex/gpt-5.4")
    assert entry is not None

    info = _build_model_info(entry)

    assert info.capabilities.has_thinking is True
    assert info.capabilities.supports_tool_execution is True
    assert info.capabilities.supports_verbosity is True
    assert info.capabilities.supports_xhigh is True
    assert info.capabilities.supports_session_cache is True


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
