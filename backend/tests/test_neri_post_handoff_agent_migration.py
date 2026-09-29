"""Deterministic guards for Neri post-handoff agent alignment."""

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
    / '9a6c8e1f4b20_align_neri_post_handoff_agents.py'
)
_SEED_PATH = _BACKEND / 'scripts' / 'seed_agents_data' / 'seed_data.json'


def _load_migration_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        'align_neri_post_handoff_agents_9a6c8e1f4b20', _MIGRATION_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_alignment_accepts_seeded_live_and_already_aligned_prompts() -> None:
    migration = _load_migration_module()
    seed = json.loads(_SEED_PATH.read_text())
    agents = {item['slug']: item for item in seed['agents']}

    assert migration._digest(migration._EXPECTED_LIVE_REVIEWER_PROMPT) == (
        'c148adb15b961cd48fd3f276fc2c604ace6a270f656ba5cbbd63ee5030c7207c'
    )

    assert migration._aligned_prompt(
        migration._REPORTER_PROMPT,
        migration._REPORTER_PROMPT,
        (migration._PREVIOUS_REPORTER_PROMPT,),
    ) == migration._REPORTER_PROMPT
    assert migration._aligned_prompt(
        agents['neri-reviewer']['system_prompt'],
        migration._REVIEWER_PROMPT,
        (
            migration._SEEDED_REVIEWER_PROMPT,
            migration._EXPECTED_LIVE_REVIEWER_PROMPT,
        ),
    ) == migration._REVIEWER_PROMPT
    assert migration._aligned_prompt(
        migration._EXPECTED_LIVE_REVIEWER_PROMPT,
        migration._REVIEWER_PROMPT,
        (migration._EXPECTED_LIVE_REVIEWER_PROMPT,),
    ) == migration._REVIEWER_PROMPT
    assert migration._aligned_prompt(
        migration._REVIEWER_PROMPT,
        migration._REVIEWER_PROMPT,
        (migration._EXPECTED_LIVE_REVIEWER_PROMPT,),
    ) == migration._REVIEWER_PROMPT


def test_alignment_rejects_an_unknown_prompt_revision() -> None:
    migration = _load_migration_module()

    with pytest.raises(RuntimeError, match='unknown pre-migration revision'):
        migration._aligned_prompt(
            'Unrecognized local prompt',
            migration._REVIEWER_PROMPT,
            (migration._EXPECTED_LIVE_REVIEWER_PROMPT,),
        )


def test_aligned_prompts_use_compact_ownership_and_inconclusive_semantics() -> None:
    migration = _load_migration_module()

    assert 'Neri deterministically owns record identities' in migration._REPORTER_PROMPT
    assert 'every distinct supported finding' in migration._REPORTER_PROMPT
    assert 'may receive inconclusive' in migration._REVIEWER_PROMPT
    assert 'never use supported or no_finding for an incomplete report' in (
        migration._REVIEWER_PROMPT
    )
    assert 'gpt-daybreak' not in migration._REVIEWER_PROMPT
