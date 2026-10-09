"""Qualification contract for the exact GPT-6.1 Sol route."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from app.constants.catalog_entries import MODEL_CATALOG
from app.llm.model_resolver import resolve_llm_model
from app.llm.providers.openai_codex_responses import _body
from app.llm.types import Context, SimpleStreamOptions

_BACKEND = Path(__file__).resolve().parents[1]


def _migration(filename: str = "c8d9e0f1a2b3_lead_with_gpt_6_1_sol.py"):
    path = _BACKEND / "alembic/versions" / filename
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_catalog_and_insert_only_seeds_match_route_capabilities_and_official_prices():
    migration = _migration()
    entries = {entry.id: entry for entry in MODEL_CATALOG}
    # 401372ee292c later pruned the keyless openai route and set Codex's 272k
    # window and availability notes, so only the still-current columns are pinned.
    assert "openai/gpt-6.1-sol" not in entries
    for row in migration._catalog_rows():
        if row["id"] not in entries:
            continue
        entry = entries[row["id"]]
        assert entry.context_window == 272_000
        assert entry.capabilities.max_output_tokens == 128_000
        assert entry.release_date is None
        assert entry.knowledge_cutoff == "2026-04-30"
        assert entry.cost.input_per_m == row["input_cost"]
        assert entry.cost.output_per_m == row["output_cost"]
        assert entry.cost.cache_read_per_million == row["cache_read"]
        assert entry.cost.cache_write_per_million == row["cache_write"]
        assert entry.capabilities.supports_tool_execution == row["tools"]
        assert entry.capabilities.supports_session_cache == row["session_cache"]


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
    alignment = _migration("9a6c8e1f4b20_align_neri_post_handoff_agents.py")
    # Pin the historical predecessor independently of current role seed edits.
    previous = alignment._REVIEWER_PROMPT
    assert migration._digest(previous) == migration._REVIEWER_DIGEST
    desired = migration._reviewer_prompt(previous)
    assert desired == previous.replace(migration._OLD_IDENTITY, migration._NEW_IDENTITY)
    assert migration._reviewer_prompt(desired) == desired
    assert migration._reviewer_prompt(desired, reverse=True) == previous
    assert migration._reviewer_prompt(previous, reverse=True) == previous
    for reverse in (False, True):
        for prompt in (previous, desired):
            with pytest.raises(RuntimeError, match="unknown model-migration revision"):
                migration._reviewer_prompt(prompt + " altered boundary", reverse=reverse)


def test_codex_preserves_supported_effort_and_clamps_minimal():
    model = resolve_llm_model("codex/gpt-6.1-sol", "codex")
    assert model.api == "openai-codex-responses"
    for effort in ("low", "medium", "high", "xhigh"):
        assert _body(model, Context(messages=[]), SimpleStreamOptions(reasoning=effort))["reasoning"]["effort"] == effort
    # The catalog thinking_level_map clamps minimal, which Codex does not offer.
    assert _body(model, Context(messages=[]), SimpleStreamOptions(reasoning="minimal"))["reasoning"]["effort"] == "low"
