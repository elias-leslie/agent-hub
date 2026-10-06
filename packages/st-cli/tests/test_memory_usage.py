"""Memory authoring guidance is available through the portable usage registry."""

from __future__ import annotations

import pytest
from st_sdk.usage import collect_usage_specs

from agent_hub_st.memory import app

SURFACES = ("st.memory.save", "st.memory.search", "st.memory.update")


def test_memory_usage_specs_expose_authoring_workflow() -> None:
    specs = collect_usage_specs(app)

    assert {spec.surface for spec in specs} == set(SURFACES)
    assert all(spec.on_demand == "memory authoring" for spec in specs)
    assert all(spec.to_dict()["on_demand"] == "memory authoring" for spec in specs)


@pytest.mark.parametrize("surface", SURFACES)
def test_memory_guidance_remains_available_by_exact_surface(surface: str) -> None:
    matches = [spec.to_dict() for spec in collect_usage_specs(app) if spec.surface == surface]

    assert len(matches) == 1
    assert matches[0]["surface"] == surface
    assert matches[0]["on_demand"] == "memory authoring"
    assert matches[0]["cmd"].startswith(surface.replace(".", " "))
    assert matches[0]["when"]
    assert matches[0]["precautions"]
    assert matches[0]["tier"] == "mandate"
