"""Provider ids and thinking levels come from the catalog, not provider code."""

from __future__ import annotations

import importlib.util
import json
from dataclasses import replace
from pathlib import Path

import pytest

from app.constants import catalog
from app.llm.model_resolver import resolve_llm_model, upstream_model_id
from app.llm.providers.openai_codex_responses import _body
from app.llm.types import Context, SimpleStreamOptions
from tests.model_ids import MODEL_CATALOG

_BACKEND = Path(__file__).resolve().parents[2]


def _effort(model_id: str, level: str) -> str:
    model = resolve_llm_model(model_id, "codex")
    return _body(model, Context(messages=[]), SimpleStreamOptions(reasoning=level))["reasoning"]["effort"]


@pytest.mark.parametrize("entry", [e for e in MODEL_CATALOG if e.provider == "codex"], ids=lambda e: e.id)
def test_every_codex_model_keeps_xhigh_and_clamps_minimal(entry) -> None:
    assert entry.capabilities.supports_xhigh
    assert _effort(entry.id, "xhigh") == "xhigh"
    assert _effort(entry.id, "minimal") == "low"


def test_unsupported_level_in_catalog_map_fails_before_dispatch() -> None:
    model = replace(resolve_llm_model("codex/gpt-6-luna", "codex"), thinking_level_map={"xhigh": None})
    with pytest.raises(ValueError, match="does not support xhigh"):
        _body(model, Context(messages=[]), SimpleStreamOptions(reasoning="xhigh"))


def test_upstream_id_comes_from_catalog_row() -> None:
    assert upstream_model_id("cloudflare/gpt-oss-120b", "cloudflare") == "@cf/openai/gpt-oss-120b"
    assert resolve_llm_model("nvidia/glm-5.3", "nvidia").id == "z-ai/glm-5.3"
    # Uncatalogued ids fall back to the id minus its provider prefix.
    assert upstream_model_id("cloudflare/some-new-model", "cloudflare") == "some-new-model"


def test_runtime_catalog_row_change_needs_no_code_change() -> None:
    entries, aliases = list(catalog.MODEL_CATALOG), dict(catalog.MODEL_ALIASES)
    renamed = [
        replace(e, upstream_id="z-ai/glm-5.3-0901") if e.id == "nvidia/glm-5.3" else e
        for e in entries
    ]
    try:
        catalog.replace_runtime_model_catalog(renamed, aliases)
        assert resolve_llm_model("nvidia/glm-5.3", "nvidia").id == "z-ai/glm-5.3-0901"
    finally:
        catalog.replace_runtime_model_catalog(entries, aliases)


def test_migration_backfills_the_catalog_values() -> None:
    path = _BACKEND / "alembic/versions/f35aa7ed2c9a_catalog_upstream_ids_and_thinking_levels.py"
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    catalog_upstream_ids = {e.id: e.upstream_id for e in MODEL_CATALOG if e.upstream_id}
    assert catalog_upstream_ids == {
        **migration._UPSTREAM_IDS,
        "codex/gpt-5.6-sol-daybreak-blue": "gpt-5.6-sol",
    }
    # 43f0a2fd606f later removed some of these models and added Claude 5 rows.
    later = json.loads(
        (_BACKEND / "alembic/versions/43f0a2fd606f_claude_cli_routes_and_codex_successors.json").read_text()
    )
    removed = {row["id"] for row in later["deleted_models"]}
    added = {row["id"] for row in later["new_models"] if row["thinking_level_map"]}
    # b7f1c2d3e4a5 deactivated Fable and dropped it from the seed catalog.
    added -= {"claude-fable-5-1"}
    removed.add("codex/gpt-daybreak-blue-latest")
    added.add("codex/gpt-5.6-sol-daybreak-blue")
    assert set(migration._MINIMAL_AS_LOW_MODELS) - removed | added == {
        e.id for e in MODEL_CATALOG if e.capabilities.thinking_level_map
    }
    level_maps = {str(e.capabilities.thinking_level_map) for e in MODEL_CATALOG}
    assert level_maps <= {"None", str(migration._MINIMAL_AS_LOW)}


def test_codex_request_carries_the_catalog_access_program() -> None:
    daybreak = resolve_llm_model("codex/gpt-5.6-sol-daybreak-blue", "codex")
    body = _body(daybreak, Context(messages=[]), None)
    assert body["model"] == "gpt-5.6-sol"
    assert body["access_programs"] == {"cyber": "daybreak_blue"}
    assert upstream_model_id("codex-daybreak", "codex") == "gpt-5.6-sol"
    assert not any("gpt-daybreak-" in entry.id for entry in MODEL_CATALOG)
    plain = resolve_llm_model("codex/gpt-6.1-sol", "codex")
    assert "access_programs" not in _body(plain, Context(messages=[]), None)


def test_claude_models_route_through_the_cli_provider() -> None:
    model = resolve_llm_model("claude-sonnet-5-5", "claude")
    assert model.api == "claude-code-cli"
    assert model.thinking_level_map == {"minimal": "low"}
