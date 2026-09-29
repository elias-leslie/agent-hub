"""Deterministic guards for the Neri reporter citation correction."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
_MIGRATION_PATH = (
    _BACKEND
    / 'alembic'
    / 'versions'
    / 'b7c8d9e0f1a2_clarify_neri_reporter_source_citations.py'
)
_SEED_PATH = _BACKEND / 'scripts' / 'seed_agents_data' / 'seed_data.json'


def _load_migration_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        'clarify_neri_reporter_source_citations_b7c8d9e0f1a2', _MIGRATION_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_prompt_upgrade_is_exact_reversible_and_seeded() -> None:
    migration = _load_migration_module()
    seed = json.loads(_SEED_PATH.read_text())
    reporter = next(item for item in seed['agents'] if item['slug'] == 'neri-reporter')
    current = reporter['system_prompt']

    assert migration._digest(current) in {
        migration._PREVIOUS_DIGEST,
        migration._DESIRED_DIGEST,
    }
    desired = migration._upgraded_prompt(current)
    assert migration._digest(desired) == migration._DESIRED_DIGEST
    assert migration._CITATION_SENTENCE in desired
    assert migration._PREVIOUS_SENTENCE not in desired
    assert migration._digest(migration._downgraded_prompt(desired)) == (
        migration._PREVIOUS_DIGEST
    )


def test_prompt_upgrade_rejects_unknown_revision() -> None:
    migration = _load_migration_module()

    with pytest.raises(RuntimeError, match='unknown pre-migration revision'):
        migration._upgraded_prompt('Unrecognized reporter prompt')
