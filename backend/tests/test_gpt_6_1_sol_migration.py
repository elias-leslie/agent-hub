"""Qualification contract for the exact GPT-6.1 Sol route."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from app.constants.catalog_entries import MODEL_CATALOG
from app.llm.model_resolver import resolve_llm_model
from app.llm.providers.openai_codex_responses import _body
from app.llm.providers.openai_completions import OpenAICompletionsOptions, _Compat, build_params
from app.llm.types import Context, SimpleStreamOptions, Tool

_BACKEND = Path(__file__).resolve().parents[1]


def _migration():
    path = _BACKEND / "alembic/versions/c8d9e0f1a2b3_lead_with_gpt_6_1_sol.py"
    spec = importlib.util.spec_from_file_location("gpt61_migration", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_catalog_and_insert_only_seeds_match_route_capabilities_and_official_prices():
    migration = _migration()
    entries = {entry.id: entry for entry in MODEL_CATALOG}
    for row in migration._catalog_rows():
        entry = entries[row["id"]]
        assert entry.context_window == 1_050_000
        assert entry.capabilities.max_output_tokens == 128_000
        assert entry.release_date is None
        assert entry.knowledge_cutoff == "2026-04-30"
        assert entry.cost.input_per_m == row["input_cost"]
        assert entry.cost.output_per_m == row["output_cost"]
        assert entry.cost.cache_read_per_million == row["cache_read"]
        assert entry.cost.cache_write_per_million == row["cache_write"]
        assert entry.capabilities.supports_tool_execution == row["tools"]
        assert entry.capabilities.supports_session_cache == row["session_cache"]
        assert entry.availability == row["availability"]


def test_routes_accept_exact_preimages_and_reject_unknown_configuration():
    migration = _migration()
    for slug, (model, effort, fallbacks, escalation, desired_effort) in migration._ROUTES.items():
        previous = {"primary_model_id": model, "thinking_level": effort,
                    "fallback_models": fallbacks, "escalation_model_id": escalation}
        migration._check_route(slug, previous)
        migration._check_route(slug, {**previous, "primary_model_id": migration._MODEL_ID,
                                     "thinking_level": desired_effort, "fallback_models": [],
                                     "escalation_model_id": None})
        with pytest.raises(RuntimeError, match="unknown model-migration revision"):
            migration._check_route(slug, {**previous, "primary_model_id": "unrecognized/model"})
    assert "neri-hunter" not in migration._ROUTES


def test_review_prompt_identity_changes_without_other_semantic_changes():
    migration = _migration()
    seeds = json.loads((_BACKEND / "scripts/seed_agents_data/seed_data.json").read_text())
    reviewer = next(agent for agent in seeds["agents"] if agent["slug"] == "neri-reviewer")
    previous = migration._reviewer_prompt(reviewer["system_prompt"], reverse=True)
    desired = migration._reviewer_prompt(previous)
    assert desired == previous.replace(migration._OLD_IDENTITY, migration._NEW_IDENTITY)
    assert migration._reviewer_prompt(desired) == desired
    assert migration._reviewer_prompt(desired, reverse=True) == previous
    with pytest.raises(RuntimeError, match="unknown model-migration revision"):
        migration._reviewer_prompt(previous + " altered boundary")


def test_codex_preserves_supported_effort_and_rejects_minimal():
    model = resolve_llm_model("codex/gpt-6.1-sol", "codex")
    assert model.api == "openai-codex-responses"
    for effort in ("low", "medium", "high", "xhigh"):
        assert _body(model, Context(messages=[]), SimpleStreamOptions(reasoning=effort))["reasoning"]["effort"] == effort
    with pytest.raises(ValueError, match="does not support minimal"):
        _body(model, Context(messages=[]), SimpleStreamOptions(reasoning="minimal"))


def test_metered_chat_route_rejects_tools_and_minimal_before_dispatch():
    model = resolve_llm_model("openai/gpt-6.1-sol", "openai")
    with pytest.raises(ValueError, match="requires a Responses route"):
        build_params(model, Context(messages=[], tools=[Tool(name="read", description="read", parameters={})]),
                     None, _Compat(), "none")
    with pytest.raises(ValueError, match="does not support minimal"):
        build_params(model, Context(messages=[]), OpenAICompletionsOptions(reasoning_effort="minimal"),
                     _Compat(), "none")
