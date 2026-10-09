"""Contract for the inactive-agent deletion migration (d1e2f3a4b5c6)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "alembic/versions/d1e2f3a4b5c6_delete_inactive_agents.py"
_SEED = Path(__file__).resolve().parents[1] / "scripts/seed_agents_data/seed_data.json"
_DELETED = {
    "auditor", "extractor", "fitness-bear-v1", "fitness-bull-v1", "fitness-judge-v1",
    "fitness-skeptic-v1", "fixer", "gemini-billing-probe", "kimi-code-test", "market-pulse-analyst",
    "memory-curator", "minimax-plan-test", "minimax-tester", "pixel-art-critic", "qa",
    "risk-aggressive-v1", "risk-conservative-v1",
}


def _migration():
    spec = importlib.util.spec_from_file_location(_PATH.stem, _PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_preimage_holds_only_the_inactive_agents_and_their_cascaded_rows():
    module = _migration()
    assert module.down_revision == "c4d5e6f7a8b9"
    data = module._data()
    agents = data["agents"]
    assert {agent["slug"] for agent in agents} == _DELETED
    assert all(agent["is_active"] is False for agent in agents)
    ids = set(module._agent_ids(data))
    for table, column in module._TABLES[1:]:
        assert data[table], table
        assert {row[column] for row in data[table]} <= ids, table


def test_downgrade_restores_parents_before_children():
    assert [table for table, _ in _migration()._TABLES] == [
        "agents", "prompts", "agent_prompts", "agent_versions",
    ]


def test_seed_cannot_recreate_deleted_agents():
    seed = json.loads(_SEED.read_text())
    assert not {agent["slug"] for agent in seed["agents"]} & _DELETED
