"""Tests for model catalog API helpers."""

from app.api.models import _build_model_info
from app.constants.catalog import get_model_entry


def test_build_model_info_includes_extended_capabilities() -> None:
    entry = get_model_entry("codex/gpt-5.4")
    assert entry is not None

    info = _build_model_info(entry)

    assert info.capabilities.has_thinking is True
    assert info.capabilities.supports_tool_execution is True
    assert info.capabilities.supports_verbosity is True
    assert info.capabilities.supports_xhigh is True
    assert info.capabilities.supports_session_cache is True
