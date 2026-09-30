"""Exact route and prompt guards for the passive Daybreak reviewer."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from app.llm.model_resolver import resolve_llm_model
from app.llm.providers.openai_codex_responses import _body
from app.llm.types import Context, SimpleStreamOptions

_BACKEND = Path(__file__).resolve().parents[1]


def _migration():
    path = _BACKEND / "alembic/versions/d9e0f1a2b3c4_pin_neri_reviewer_daybreak.py"
    spec = importlib.util.spec_from_file_location("neri_daybreak_migration", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_exact_route_and_seed_preserve_reporter_and_disable_fallback():
    migration = _migration()
    seed = json.loads((_BACKEND / "scripts/seed_agents_data/seed_data.json").read_text())
    agents = {agent["slug"]: agent for agent in seed["agents"]}
    reviewer = agents["neri-reviewer"]
    previous = {
        "primary_model_id": migration._PREVIOUS_MODEL, "thinking_level": "high",
        "fallback_models": [], "escalation_model_id": None, "is_active": True,
    }
    migration._check_route(previous)
    migration._check_route({**previous, **reviewer})
    assert reviewer["primary_model_id"] == migration._MODEL
    assert reviewer["thinking_level"] == "high"
    assert reviewer["fallback_models"] == []
    assert reviewer["escalation_model_id"] is None
    assert agents["neri-reporter"]["primary_model_id"] == "codex/gpt-6.1-sol"
    assert agents["neri-reporter"]["thinking_level"] == "medium"
    assert agents["neri-reporter"]["fallback_models"] == []
    for change in (
        {"primary_model_id": "codex/gpt-6-astra"}, {"thinking_level": "medium"},
        {"fallback_models": ["codex/gpt-6.1-sol"]}, {"fallback_models": None},
        {"escalation_model_id": "codex/gpt-6.1-sol"}, {"is_active": False},
    ):
        with pytest.raises(RuntimeError, match="unknown Daybreak-route revision"):
            migration._check_route({**previous, **change})


def test_prompt_change_is_exact_reversible_and_rejects_unrecognized_revisions():
    migration = _migration()
    seed = json.loads((_BACKEND / "scripts/seed_agents_data/seed_data.json").read_text())
    desired = next(agent for agent in seed["agents"] if agent["slug"] == "neri-reviewer")["system_prompt"]
    previous = migration._reviewer_prompt(desired, reverse=True)
    assert migration._digest(previous) == migration._PREVIOUS_DIGEST
    assert migration._digest(desired) == migration._DIGEST
    assert desired == previous.replace(migration._PREVIOUS_IDENTITY, migration._IDENTITY)
    assert migration._reviewer_prompt(previous) == desired
    assert migration._reviewer_prompt(desired) == desired
    with pytest.raises(RuntimeError, match="unknown Daybreak-route revision"):
        migration._reviewer_prompt(previous + " altered review requirement")


def test_codex_daybreak_resolution_preserves_exact_model_and_high_effort():
    model = resolve_llm_model("codex/gpt-daybreak-blue-latest", "codex")
    body = _body(model, Context(messages=[]), SimpleStreamOptions(reasoning="high"))
    assert model.api == "openai-codex-responses"
    assert body["model"] == "gpt-daybreak-blue-latest"
    assert body["reasoning"]["effort"] == "high"
