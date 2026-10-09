from __future__ import annotations

import pytest

from app.llm.model_resolver import resolve_llm_model
from app.llm.providers.google import _disabled_thinking_config, _get_thinking_level


@pytest.mark.parametrize(
    ("model_id", "expected"),
    [
        ("gemini-3.1-flash-lite", "MINIMAL"),
        ("gemini-3.5-flash", "MINIMAL"),
        ("gemini-3.6-flash", "MINIMAL"),
        ("gemini-3.7-flash", "LOW"),
        ("gemini-3.8-flash", "LOW"),
    ],
)
def test_minimal_thinking_clamps_only_where_gemini_rejects_it(model_id: str, expected: str) -> None:
    model = resolve_llm_model(model_id, "gemini")

    assert _get_thinking_level("minimal", model) == expected
    assert _disabled_thinking_config(model) == {"thinking_level": expected}
