"""Contract for the Claude CLI routes and Codex successor migration (43f0a2fd606f)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from app.constants.catalog_entries import MODEL_CATALOG
from app.services.model_catalog_service import _entry_values, _seed_aliases

_BACKEND = Path(__file__).resolve().parents[1]
_DAYBREAK = "codex/gpt-daybreak-blue-latest"


def _migration():
    path = _BACKEND / "alembic/versions/43f0a2fd606f_claude_cli_routes_and_codex_successors.py"
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _data() -> dict:
    return _migration()._data()


def test_active_new_rows_match_the_insert_only_seed_catalog():
    data = _data()
    catalog = {e.id: _entry_values(e, i) for i, e in enumerate(MODEL_CATALOG, start=1)}
    assert not {r["id"] for r in data["deleted_models"]} & set(catalog)
    for row in data["new_models"]:
        if row["is_active"]:
            expected = {k: v for k, v in catalog[row["id"]].items() if k != "sort_order"}
            assert {k: v for k, v in row.items() if k != "sort_order"} == expected
    for column, change in data["updated_models"][_DAYBREAK].items():
        assert catalog[_DAYBREAK][column] == change["after"]
    aliases = _seed_aliases(MODEL_CATALOG)
    for alias in data["new_aliases"]:
        if alias["model_id"] in catalog:
            assert aliases[alias["alias"]] == (alias["model_id"], alias["alias_type"])


def test_unfunded_subscriptions_stay_catalogued_but_inactive():
    restored = {r["id"]: r for r in _data()["new_models"] if r["provider"] in {"kimi-code", "minimax"}}
    assert {"kimi-code/kimi-for-coding", "minimax/MiniMax-M3"} <= set(restored)
    assert all(not row["is_active"] and "top-up" in row["availability"] for row in restored.values())


def test_daybreak_blue_requires_its_access_program():
    change = _data()["updated_models"][_DAYBREAK]
    assert change["access_programs"]["after"] == {"cyber": "daybreak_blue"}
    assert "deprecated_alias_upstream" not in change["availability"]["after"]


def test_routes_leave_no_reference_to_removed_models():
    data = _data()
    removed = {r["id"] for r in data["deleted_models"]}
    known = {e.id for e in MODEL_CATALOG} | {r["id"] for r in data["new_models"]}
    for slug, route in data["routes"].items():
        after = route["after"]
        ids = {after["primary_model_id"], *after["fallback_models"], after["escalation_model_id"]} - {None}
        assert not ids & removed, slug
        assert ids <= known, (slug, ids - known)


def test_design_critics_lead_with_claude_then_codex():
    routes = _data()["routes"]
    for slug in ("game-art-critic", "designer", "ui-mockup-designer"):
        after = routes[slug]["after"]
        assert after["primary_model_id"].startswith("claude-")
        assert after["fallback_models"][0].startswith("codex/")
    art = routes["game-art-critic"]["after"]
    assert not [m for m in [art["primary_model_id"], *art["fallback_models"]] if m.startswith("xai/")]
    # Claude and Codex take no audio, so the audio critic stays on audio-capable Gemini.
    audio = routes["game-audio-critic"]["after"]
    assert audio["primary_model_id"].startswith("gemini-")


def test_routes_accept_exact_preimage_and_reject_unknown_configuration():
    migration = _migration()
    for slug, route in migration._data()["routes"].items():
        for state in ("before", "after"):
            migration._check_route(slug, dict(route[state]), route[state])
        with pytest.raises(RuntimeError, match="unknown model-migration revision"):
            migration._check_route(
                slug, {**route["before"], "primary_model_id": "unrecognized/model"}, route["before"]
            )


def test_migration_strings_fit_their_columns():
    from sqlalchemy import String

    from app.models.model_catalog import ModelAlias, ModelCatalogEntry

    data = _data()
    rows = [
        *(dict(r) for r in data["new_models"]),
        *({c: v["after"] for c, v in changes.items()} for changes in data["updated_models"].values()),
    ]
    columns = ModelCatalogEntry.__table__.columns
    for row in rows:
        for column, value in row.items():
            kind = columns[column].type
            if isinstance(kind, String) and kind.length and isinstance(value, str):
                assert len(value) <= kind.length, (column, len(value), value)
    alias_columns = ModelAlias.__table__.columns
    for alias in data["new_aliases"]:
        for column, value in alias.items():
            kind = alias_columns[column].type
            if isinstance(kind, String) and kind.length:
                assert len(value) <= kind.length, (column, value)
