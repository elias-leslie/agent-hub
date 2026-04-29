"""Tests for startup-time agent model reconciliation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models import Agent
from app.services.agent_model_reconciliation_service import (
    reconcile_agent_models_to_available_providers,
)
from app.services.credential_manager import CredentialManager


def _db_result_for(agents: list[Agent]) -> MagicMock:
    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = agents
    result.scalars.return_value = scalars
    return result


def _agent(
    *,
    slug: str,
    primary_model_id: str,
    fallback_models: list[str] | None = None,
    escalation_model_id: str | None = None,
) -> Agent:
    return Agent(
        slug=slug,
        name=slug.title(),
        description=None,
        system_prompt="test",
        primary_model_id=primary_model_id,
        fallback_models=fallback_models or [],
        escalation_model_id=escalation_model_id,
        strategies={},
        temperature=0.1,
        thinking_level="medium",
        verbosity_level=None,
        is_active=True,
        is_coding_agent=False,
        memory_config=None,
        max_concurrency=None,
        max_subagent_concurrency=None,
        daily_token_budget=None,
        hourly_request_limit=None,
        timeout_seconds=None,
        version=1,
    )


class TestReconcileAgentModelsToAvailableProviders:
    def setup_method(self) -> None:
        CredentialManager.reset()

    @pytest.mark.asyncio
    async def test_promotes_available_existing_fallback_to_primary(self) -> None:
        credential_manager = CredentialManager.get_instance()
        credential_manager.set("claude", "api_key", "anthropic-key")
        agent = _agent(
            slug="persona",
            primary_model_id="codex/gpt-5.4",
            fallback_models=["claude-sonnet-4-6"],
            escalation_model_id="claude-sonnet-4-6",
        )
        mock_db = AsyncMock()
        mock_db.execute.return_value = _db_result_for([agent])

        with patch(
            "app.services.agent_model_reconciliation_service.AgentCache"
        ) as mock_cache_class:
            mock_cache = AsyncMock()
            mock_cache_class.return_value = mock_cache
            changed = await reconcile_agent_models_to_available_providers(mock_db)

        assert changed == ["persona"]
        assert agent.primary_model_id == "claude-sonnet-4-6"
        assert agent.fallback_models == ["claude-opus-4-7"]
        assert agent.escalation_model_id == "claude-sonnet-4-6"
        mock_db.commit.assert_awaited_once()
        mock_cache.invalidate.assert_awaited_once_with("persona")
        mock_cache.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_maps_unavailable_chain_to_openai_when_only_openai_exists(self) -> None:
        credential_manager = CredentialManager.get_instance()
        credential_manager.set("openai", "api_key", "openai-key")
        agent = _agent(
            slug="ideator-public",
            primary_model_id="claude-opus-4-6",
            fallback_models=["claude-sonnet-4-6", "codex/gpt-5.4"],
        )
        mock_db = AsyncMock()
        mock_db.execute.return_value = _db_result_for([agent])

        with patch(
            "app.services.agent_model_reconciliation_service.AgentCache"
        ) as mock_cache_class:
            mock_cache = AsyncMock()
            mock_cache_class.return_value = mock_cache
            changed = await reconcile_agent_models_to_available_providers(mock_db)

        assert changed == ["ideator-public"]
        assert agent.primary_model_id.startswith("openai/")
        assert all(model.startswith("openai/") for model in agent.fallback_models)
        mock_db.commit.assert_awaited_once()
        mock_cache.invalidate.assert_awaited_once_with("ideator-public")
        mock_cache.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_codex_primary_agents_gain_codex_and_working_non_codex_fallbacks(self) -> None:
        credential_manager = CredentialManager.get_instance()
        credential_manager.set("codex", "oauth_token", "codex-token")
        credential_manager.set("claude", "api_key", "anthropic-key")
        credential_manager.set("xai", "api_key", "xai-key")
        agent = _agent(
            slug="chat",
            primary_model_id="codex/gpt-5.4",
            fallback_models=["claude-haiku-4-5", "gemini-3-flash-preview"],
        )
        mock_db = AsyncMock()
        mock_db.execute.return_value = _db_result_for([agent])

        with patch(
            "app.services.agent_model_reconciliation_service.AgentCache"
        ) as mock_cache_class:
            mock_cache = AsyncMock()
            mock_cache_class.return_value = mock_cache
            changed = await reconcile_agent_models_to_available_providers(mock_db)

        assert changed == ["chat"]
        assert agent.primary_model_id == "codex/gpt-5.5"
        assert agent.fallback_models[0] == "codex/gpt-5.3-codex-spark"
        assert any(model.startswith("codex/") for model in agent.fallback_models)
        assert any(model.startswith("xai/") for model in agent.fallback_models)
        assert any(model.startswith("claude-") for model in agent.fallback_models)
        mock_db.commit.assert_awaited_once()
        mock_cache.invalidate.assert_awaited_once_with("chat")
        mock_cache.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_skips_ignored_design_image_and_pinned_refactor_agents(self) -> None:
        credential_manager = CredentialManager.get_instance()
        credential_manager.set("codex", "oauth_token", "codex-token")
        ignored_agents = [
            _agent(slug="designer", primary_model_id="claude-opus-4-6"),
            _agent(slug="ux-polisher", primary_model_id="claude-opus-4-6"),
            _agent(slug="image-gen", primary_model_id="nvidia/flux.1-dev", fallback_models=["minimax/image-01"]),
            _agent(
                slug="refactor",
                primary_model_id="codex/gpt-5.4",
                fallback_models=["codex/gpt-5.3-codex-spark", "claude-sonnet-4-6"],
            ),
        ]
        mock_db = AsyncMock()
        mock_db.execute.return_value = _db_result_for(ignored_agents)

        with patch(
            "app.services.agent_model_reconciliation_service.AgentCache"
        ) as mock_cache_class:
            mock_cache = AsyncMock()
            mock_cache_class.return_value = mock_cache
            changed = await reconcile_agent_models_to_available_providers(mock_db)

        assert changed == []
        assert ignored_agents[0].primary_model_id == "claude-opus-4-6"
        assert ignored_agents[1].primary_model_id == "claude-opus-4-6"
        assert ignored_agents[2].primary_model_id == "nvidia/flux.1-dev"
        assert ignored_agents[3].primary_model_id == "codex/gpt-5.4"
        assert ignored_agents[3].fallback_models[0] == "codex/gpt-5.3-codex-spark"
        mock_db.commit.assert_not_awaited()
        mock_cache.invalidate.assert_not_called()
        mock_cache.close.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_noops_when_no_text_provider_credentials_exist(self) -> None:
        agent = _agent(slug="persona", primary_model_id="codex/gpt-5.4")
        mock_db = AsyncMock()
        mock_db.execute.return_value = _db_result_for([agent])

        changed = await reconcile_agent_models_to_available_providers(mock_db)

        assert changed == []
        mock_db.execute.assert_not_awaited()
        mock_db.commit.assert_not_awaited()
