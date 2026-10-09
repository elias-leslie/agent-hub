"""Contract for the 2026-10-09 catalog refresh and route migration."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from app.constants.catalog_entries import MODEL_CATALOG
from app.services.model_catalog_service import _entry_values, _seed_aliases

_BACKEND = Path(__file__).resolve().parents[1]


def _migration():
    path = _BACKEND / "alembic/versions/401372ee292c_refresh_model_catalog_and_routes.py"
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_postimage_matches_the_insert_only_seed_catalog():
    data = _migration()._data()
    catalog = {e.id: _entry_values(e, i) for i, e in enumerate(MODEL_CATALOG, start=1)}

    assert not {r["id"] for r in data["deleted_models"]} & set(catalog)
    # f35aa7ed2c9a adds upstream_id and thinking_level_map afterwards.
    later = {"upstream_id", "thinking_level_map"}
    for row in data["new_models"]:
        assert row == {k: v for k, v in catalog[row["id"]].items() if k not in later}
    for model_id, changes in data["updated_models"].items():
        for column, change in changes.items():
            assert catalog[model_id][column] == change["after"]
    aliases = _seed_aliases(MODEL_CATALOG)
    for alias in data["new_aliases"]:
        assert aliases[alias["alias"]] == (alias["model_id"], alias["alias_type"])


def test_routes_point_only_at_catalogued_models():
    data = _migration()._data()
    catalog = {e.id for e in MODEL_CATALOG}
    for slug, route in data["routes"].items():
        after = route["after"]
        ids = [after["primary_model_id"], *after["fallback_models"], after["escalation_model_id"]]
        missing = [i for i in ids if i and i not in catalog]
        assert not missing or not after["is_active"], (slug, missing)

    routes = data["routes"]
    assert routes["worker"]["after"]["primary_model_id"] == "codex/gpt-6-luna"
    assert routes["jobs-company"]["after"]["primary_model_id"] == "codex/gpt-5.6-terra"
    assert routes["jobs-company"]["before"]["primary_model_id"] == "codex/gpt-5.4-mini"


def test_routes_accept_exact_preimage_and_reject_unknown_configuration():
    migration = _migration()
    for slug, route in migration._data()["routes"].items():
        for state in ("before", "after"):
            migration._check_route(slug, dict(route[state]), route[state])
        with pytest.raises(RuntimeError, match="unknown model-migration revision"):
            migration._check_route(
                slug, {**route["before"], "primary_model_id": "unrecognized/model"}, route["before"]
            )


def test_fast_agents_gain_a_catalogued_subscription_fallback():
    path = _BACKEND / "alembic/versions/ac0650fc9388_subscription_fallback_for_fast_agents.py"
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    catalog = {e.id: e for e in MODEL_CATALOG}
    refreshed = _migration()._data()["routes"]
    for slug, (previous, desired) in migration._ROUTES.items():
        assert refreshed[slug]["after"]["fallback_models"] == previous
        assert desired[0] == "codex/gpt-6-luna"
        assert all(model in catalog for model in desired)
