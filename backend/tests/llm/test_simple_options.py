from __future__ import annotations

from typing import Any

from app.llm.simple_options import build_base_options
from app.llm.types import Model, ModelCost


def _model(max_tokens: int) -> Model[Any]:
    return Model[Any](
        id="large-output-model",
        name="Large Output Model",
        api="faux",
        provider="faux",
        base_url=None,
        reasoning=False,
        input=["text"],
        cost=ModelCost(input=0.0, output=0.0, cache_read=0.0, cache_write=0.0),
        context_window=200_000,
        max_tokens=max_tokens,
    )


def test_build_base_options_uses_catalog_output_limit_without_local_32k_cap() -> None:
    options = build_base_options(_model(131_072))

    assert options.max_tokens == 131_072
