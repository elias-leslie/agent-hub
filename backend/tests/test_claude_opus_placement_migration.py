"""Contract for the Claude Opus 5.5 placement migration (c4d5e6f7a8b9)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
_PATH = _BACKEND / "alembic/versions/c4d5e6f7a8b9_place_claude_opus_on_defensive_review.py"
_SEED = _BACKEND / "scripts/seed_agents_data/seed_data.json"


def _migration():
    spec = importlib.util.spec_from_file_location(_PATH.stem, _PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_opus_reviewer_reuses_the_neri_reviewer_contract_exactly():
    module = _migration()
    assert module.down_revision == "b7f1c2d3e4a5"
    seed = {agent["slug"]: agent for agent in json.loads(_SEED.read_text())["agents"]}
    # The published seed omits deployment-specific agents; compare only when present.
    if "neri-reviewer" in seed:
        reviewer = seed["neri-reviewer"]
        assert reviewer["system_prompt"] == module._SYSTEM_PROMPT
        assert reviewer["memory_config"] == json.loads(module._MEMORY_CONFIG)
    assert module._OPUS == "claude-opus-5-5"
    assert module._REVIEWER["primary_model_id"] == module._OPUS


def test_text_fits_agent_columns():
    module = _migration()
    for field, limit in (("slug", 100), ("name", 100), ("description", 100), ("thinking_level", 20)):
        assert len(module._REVIEWER[field]) <= limit, field


def test_escalation_targets_only_the_finance_review_and_synthesis_agents():
    assert set(_migration()._ESCALATED) == {"financial-document-reviewer", "investment-committee", "risk-manager"}
