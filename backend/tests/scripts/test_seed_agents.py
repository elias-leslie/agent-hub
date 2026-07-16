"""Regression tests for the strictly insert-only seed path."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from app.models.agent import Agent
from app.models.prompt import AgentPrompt, Prompt
from scripts import seed_agents as seed_module
from tests.conftest import create_mock_db_session


def _result(*, scalar: object | None = None, rows: list[object] | None = None) -> Mock:
    result = Mock()
    result.scalar_one_or_none.return_value = scalar
    result.scalars.return_value.all.return_value = rows or []
    return result


@pytest.mark.asyncio
async def test_repeated_seed_does_not_mutate_existing_agent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_file = tmp_path / "seed_data.json"
    seed_file.write_text(
        json.dumps(
            {
                "agents": [
                    {
                        "slug": "auditor",
                        "name": "Seed Name",
                        "system_prompt": "seed content",
                        "primary_model_id": "codex/gpt-5.5",
                    }
                ],
                "prompts": [],
                "agent_prompt_assignments": [],
                # Old exports may still contain this key. It must be inert.
                "deactivate_slugs": ["auditor"],
            }
        )
    )
    monkeypatch.setattr(seed_module, "SEED_FILE", seed_file)
    sync_prompt = AsyncMock()
    monkeypatch.setattr(seed_module, "sync_agent_system_prompt", sync_prompt)
    existing = Agent(
        slug="auditor",
        name="Live Name",
        system_prompt="live content",
        primary_model_id="cloudflare/gemma-4-26b",
        is_active=True,
        version=7,
    )
    existing.id = 42
    db = create_mock_db_session()
    db.execute.return_value = _result(scalar=existing)

    created = await seed_module.seed_agents(db)

    assert created == 0
    assert existing.name == "Live Name"
    assert existing.system_prompt == "live content"
    assert existing.primary_model_id == "cloudflare/gemma-4-26b"
    assert existing.is_active is True
    assert existing.version == 7
    db.add.assert_not_called()
    sync_prompt.assert_not_awaited()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_new_deactivated_slug_is_inserted_inactive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_file = tmp_path / "seed_data.json"
    seed_file.write_text(
        json.dumps(
            {
                "agents": [
                    {
                        "slug": "auditor",
                        "name": "Legacy Auditor",
                        "system_prompt": "audit",
                        "primary_model_id": "codex/gpt-5.5",
                    }
                ],
                "prompts": [],
                "agent_prompt_assignments": [],
                "deactivate_slugs": ["auditor"],
            }
        )
    )
    monkeypatch.setattr(seed_module, "SEED_FILE", seed_file)
    sync_prompt = AsyncMock()
    monkeypatch.setattr(seed_module, "sync_agent_system_prompt", sync_prompt)
    db = create_mock_db_session()
    db.execute.return_value = _result(scalar=None)

    created = await seed_module.seed_agents(db)

    inserted = db.add.call_args.args[0]
    assert created == 1
    assert isinstance(inserted, Agent)
    assert inserted.slug == "auditor"
    assert inserted.is_active is False
    sync_prompt.assert_awaited_once()


@pytest.mark.asyncio
async def test_repeated_prompt_seed_does_not_mutate_prompt_or_assignment() -> None:
    agent = Agent(
        slug="persona",
        name="Persona",
        system_prompt="live system content",
        primary_model_id="codex/gpt-5.5",
    )
    agent.id = 3
    prompt = Prompt(
        slug="persona-safety",
        name="Live Safety",
        content="live prompt content",
        is_global=False,
        enabled=True,
        exclude_agents=[],
        prompt_type="standard",
    )
    prompt.id = 9
    assignment = AgentPrompt(
        agent_id=agent.id,
        prompt_id=prompt.id,
        role="guardrail",
        priority=88,
    )
    assignment.id = 11
    db = create_mock_db_session()
    db.execute.side_effect = [
        _result(rows=[agent]),
        _result(scalar=prompt),
        _result(rows=[prompt]),
        _result(scalar=assignment),
    ]

    created = await seed_module._seed_prompts(
        db,
        [
            {
                "slug": prompt.slug,
                "name": "Seed Safety",
                "content": "seed prompt content",
                "enabled": False,
            }
        ],
        [
            {
                "agent_slug": agent.slug,
                "prompt_slug": prompt.slug,
                "role": "system",
                "priority": 1,
            }
        ],
    )

    assert created == 0
    assert prompt.name == "Live Safety"
    assert prompt.content == "live prompt content"
    assert prompt.enabled is True
    assert assignment.role == "guardrail"
    assert assignment.priority == 88
    db.add.assert_not_called()
    db.flush.assert_not_awaited()
