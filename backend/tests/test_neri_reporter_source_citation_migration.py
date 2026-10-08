"""Deterministic guards for the Neri reporter citation correction."""

from __future__ import annotations

import importlib.util
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


def _load_migration_module(path: Path = _MIGRATION_PATH) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        path.stem, path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_prompt_upgrade_is_exact_reversible_and_seeded() -> None:
    migration = _load_migration_module()
    alignment = _load_migration_module(_MIGRATION_PATH.with_name(
        '9a6c8e1f4b20_align_neri_post_handoff_agents.py',
    ))
    # Use the exact predecessor revision, not today's compact reporter seed.
    previous = alignment._REPORTER_PROMPT

    assert migration._digest(previous) == migration._PREVIOUS_DIGEST
    desired = migration._upgraded_prompt(previous)
    assert migration._digest(desired) == migration._DESIRED_DIGEST
    assert migration._CITATION_SENTENCE in desired
    assert migration._PREVIOUS_SENTENCE not in desired
    assert migration._upgraded_prompt(desired) == desired
    assert migration._downgraded_prompt(desired) == previous
    assert migration._downgraded_prompt(previous) == previous
    with pytest.raises(RuntimeError, match='unknown pre-migration revision'):
        migration._upgraded_prompt(previous + ' altered citation requirement')
    with pytest.raises(RuntimeError, match='unknown post-migration revision'):
        migration._downgraded_prompt(desired + ' altered citation requirement')


def test_prompt_upgrade_rejects_unknown_revision() -> None:
    migration = _load_migration_module()

    with pytest.raises(RuntimeError, match='unknown pre-migration revision'):
        migration._upgraded_prompt('Unrecognized reporter prompt')
