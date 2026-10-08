"""Deterministic guards for Neri post-handoff agent alignment."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import NoResultFound

_BACKEND = Path(__file__).resolve().parents[1]
_MIGRATION_PATH = (
    _BACKEND
    / 'alembic'
    / 'versions'
    / '9a6c8e1f4b20_align_neri_post_handoff_agents.py'
)


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

    # Historical migration preimages are immutable; current role seeds evolve
    # separately and are covered by the seed-agent policy tests.
    assert migration._digest(migration._EXPECTED_LIVE_REVIEWER_PROMPT) == (
        'c148adb15b961cd48fd3f276fc2c604ace6a270f656ba5cbbd63ee5030c7207c'
    )

    assert migration._aligned_prompt(
        migration._REPORTER_PROMPT,
        migration._REPORTER_PROMPT,
        (migration._PREVIOUS_REPORTER_PROMPT,),
    ) == migration._REPORTER_PROMPT
    assert migration._aligned_prompt(
        migration._SEEDED_REVIEWER_PROMPT,
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


def test_alignment_preserves_an_unseeded_agent_on_a_fresh_database() -> None:
    migration = _load_migration_module()
    connection = MagicMock()
    result = connection.execute.return_value
    result.scalar_one.side_effect = NoResultFound
    result.scalar_one_or_none.return_value = None

    migration._align_agent(
        connection,
        slug='neri-reviewer',
        name='Neri Reviewer System Prompt',
        description='Existing reviewer alignment only.',
        desired=migration._REVIEWER_PROMPT,
        expected=(migration._SEEDED_REVIEWER_PROMPT,),
    )

    # This migration aligns existing identities; it must neither fail a fresh
    # schema nor create a new reviewer, prompt, or binding implicitly.
    connection.execute.assert_called_once()
    statement, parameters = connection.execute.call_args.args
    assert str(statement).startswith('SELECT system_prompt FROM agents')
    assert parameters == {'slug': 'neri-reviewer'}


def test_aligned_prompts_use_compact_ownership_and_inconclusive_semantics() -> None:
    migration = _load_migration_module()

    assert 'Neri deterministically owns record identities' in migration._REPORTER_PROMPT
    assert 'every distinct supported finding' in migration._REPORTER_PROMPT
    assert 'may receive inconclusive' in migration._REVIEWER_PROMPT
    assert 'never use supported or no_finding for an incomplete report' in (
        migration._REVIEWER_PROMPT
    )
    assert 'gpt-daybreak' not in migration._REVIEWER_PROMPT
