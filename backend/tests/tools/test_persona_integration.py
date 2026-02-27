"""Integration tests for Jenny persona — tools, permissions, sandbox, and providers.

Verifies the full persona pipeline is functional:
1. All 20 persona tools dispatch correctly via DirectToolExecutor
2. Persona-sandbox working directory (bash, read_file, write_file)
3. Permission tier exemptions (persona tools bypass project tier)
4. Permission DENY at tier=off
5. Cross-project path enforcement from persona-sandbox
6. Tool handler → executor pipeline with composed permission hooks
7. Claude and Gemini provider completions with persona agent (integration-only)
"""

from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.persona import Persona
from app.services.tools.base import ToolCall, ToolDecision
from app.services.tools.direct_executor_core import DirectToolExecutor
from app.services.tools.tool_handler import (
    _compose_hooks,
    _create_cross_project_permission_hook,
    create_direct_handler,
)

# ---------------------------------------------------------------------------
# Shared test fixtures
# ---------------------------------------------------------------------------

SANDBOX_DIR = "/home/kasadis/persona-sandbox"


def _make_persona(**overrides: Any) -> MagicMock:
    """Create a mock Persona with sensible defaults."""
    defaults = {
        "id": 1,
        "agent_id": 10,
        "name": "Jenny",
        "personality": "I'm a helpful assistant.",
        "heartbeat_instructions": None,
        "user_context": "User prefers concise answers.",
        "voice_id": "en-AU-NatashaNeural",
        "voice_enabled": False,
        "heartbeat_interval_minutes": 60,
        "avatar_url": None,
        "greeting": None,
        "onboarding_complete": False,
        "onboarding_phase": "not_started",
        "session_reset_mode": "daily",
        "session_reset_hour": 9,
        "session_reset_idle_minutes": 120,
        "limits": None,
        "version": 45,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    mock = MagicMock(spec=Persona)
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


def _make_journal(**overrides: Any) -> MagicMock:
    """Create a mock Memory object for journal entries."""
    entry_type = overrides.pop("entry_type", "observation")
    defaults = {
        "content": "Observed user preference.",
        "metadata_": {"entry_type": entry_type},
        "valid_at": datetime.now(UTC),
        "created_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    mock = MagicMock()
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


def _mock_async_session(persona: Any, journal_entries: list | None = None):
    """Create a mock async_session context manager."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = persona
    mock_result.scalars.return_value.all.return_value = journal_entries or []
    mock_result.scalar.return_value = 0
    mock_db.execute.return_value = mock_result
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()

    @asynccontextmanager
    async def _session():
        yield mock_db

    return _session, mock_db


def _mock_memory_repo(journal_entries: list | None = None) -> AsyncMock:
    """Create a mock memory repository."""
    mock_repo = AsyncMock()
    mock_repo.list_by_scope_and_tier = AsyncMock(return_value=journal_entries or [])
    mock_repo.create = AsyncMock()
    return mock_repo


def _mock_embedder() -> AsyncMock:
    """Create a mock embedder for journal writes."""
    mock = AsyncMock()
    mock.embed = AsyncMock(return_value=[0.1] * 768)
    return mock


# ---------------------------------------------------------------------------
# 1. ALL 20 PERSONA TOOLS DISPATCH VIA EXECUTOR
# ---------------------------------------------------------------------------


class TestAllPersonaToolsDispatch:
    """Verify every persona tool routes through DirectToolExecutor.dispatch()."""

    @pytest.fixture
    def executor(self, tmp_path: Path) -> DirectToolExecutor:
        return DirectToolExecutor(str(tmp_path), project_id="persona-sandbox")

    @pytest.mark.asyncio
    async def test_read_personality_dispatches(self, executor: DirectToolExecutor):
        persona = _make_persona(personality="Warm and direct.")
        session_fn, _ = _mock_async_session(persona)
        with (
            patch("app.db.async_session", session_fn),
            patch(
                "app.services.persona_service.get_or_create_persona",
                new_callable=AsyncMock,
                return_value=persona,
            ),
        ):
            result = await executor.dispatch("read_personality", {})
        assert "Warm and direct." in result

    @pytest.mark.asyncio
    async def test_write_personality_dispatches(self, executor: DirectToolExecutor):
        persona = _make_persona(version=10)
        session_fn, _ = _mock_async_session(persona)
        with (
            patch("app.db.async_session", session_fn),
            patch(
                "app.services.persona_service.get_or_create_persona",
                new_callable=AsyncMock,
                return_value=persona,
            ),
        ):
            result = await executor.dispatch(
                "write_personality",
                {"personality": "New personality.", "reason": "test"},
            )
        assert "Personality updated" in result
        assert persona.version == 11

    @pytest.mark.asyncio
    async def test_write_journal_dispatches(self, executor: DirectToolExecutor):
        mock_repo = _mock_memory_repo()
        mock_emb = _mock_embedder()
        with (
            patch("app.services.memory.repository.get_memory_repository", return_value=mock_repo),
            patch("app.services.memory.embedder.get_embedder", return_value=mock_emb),
        ):
            result = await executor.dispatch(
                "write_journal",
                {"content": "Test observation.", "entry_type": "observation"},
            )
        assert "Journal entry recorded" in result
        mock_repo.create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_read_journal_dispatches(self, executor: DirectToolExecutor):
        entry = _make_journal(content="Pattern detected.", entry_type="learning")
        mock_repo = _mock_memory_repo(journal_entries=[entry])
        with patch("app.services.memory.repository.get_memory_repository", return_value=mock_repo):
            result = await executor.dispatch("read_journal", {"days_back": 7})
        assert "Pattern detected." in result

    @pytest.mark.asyncio
    async def test_search_journal_dispatches(self, executor: DirectToolExecutor):
        entry = _make_journal(content="Dark mode issue found.", entry_type="observation")
        mock_repo = _mock_memory_repo(journal_entries=[entry])
        with patch("app.services.memory.repository.get_memory_repository", return_value=mock_repo):
            result = await executor.dispatch("search_journal", {"query": "dark mode"})
        assert "Dark mode issue found." in result

    @pytest.mark.asyncio
    async def test_write_user_context_dispatches(self, executor: DirectToolExecutor):
        persona = _make_persona(version=5)
        session_fn, _ = _mock_async_session(persona)
        with (
            patch("app.db.async_session", session_fn),
            patch(
                "app.services.persona_service.get_or_create_persona",
                new_callable=AsyncMock,
                return_value=persona,
            ),
        ):
            result = await executor.dispatch(
                "write_user_context", {"user_context": "Prefers morning standups."}
            )
        assert "User context updated" in result
        assert persona.version == 6

    @pytest.mark.asyncio
    async def test_read_user_context_dispatches(self, executor: DirectToolExecutor):
        persona = _make_persona(user_context="Timezone: Australia/Sydney")
        session_fn, _ = _mock_async_session(persona)
        with (
            patch("app.db.async_session", session_fn),
            patch(
                "app.services.persona_service.get_or_create_persona",
                new_callable=AsyncMock,
                return_value=persona,
            ),
        ):
            result = await executor.dispatch("read_user_context", {})
        assert "Australia/Sydney" in result

    @pytest.mark.asyncio
    async def test_mark_memory_relevant_dispatches(self, executor: DirectToolExecutor):
        with (
            patch(
                "app.services.memory.episode_property_queries.get_episode_tags",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "app.services.memory.episode_property_setters.set_episode_tags",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            result = await executor.dispatch(
                "mark_memory_relevant", {"memory_uuid": "abc12345-uuid"}
            )
        assert "marked as persona-relevant" in result

    @pytest.mark.asyncio
    async def test_mark_memory_irrelevant_dispatches(self, executor: DirectToolExecutor):
        with (
            patch(
                "app.services.memory.episode_property_queries.get_episode_tags",
                new_callable=AsyncMock,
                return_value=["persona-relevant"],
            ),
            patch(
                "app.services.memory.episode_property_setters.set_episode_tags",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            result = await executor.dispatch(
                "mark_memory_irrelevant", {"memory_uuid": "abc12345-uuid"}
            )
        assert "Removed persona-relevant" in result

    @pytest.mark.asyncio
    async def test_submit_onboarding_dispatches(self, executor: DirectToolExecutor):
        persona = _make_persona(
            onboarding_phase="in_progress",
            onboarding_complete=False,
            user_context="Partial context.",
        )
        session_fn, _ = _mock_async_session(persona)
        with (
            patch("app.db.async_session", session_fn),
            patch(
                "app.services.persona_service.get_or_create_persona",
                new_callable=AsyncMock,
                return_value=persona,
            ),
            patch(
                "app.services.persona_service.submit_and_review_onboarding",
                new_callable=AsyncMock,
                return_value={"status": "approved", "feedback": "All criteria met."},
            ),
        ):
            result = await executor.dispatch("submit_onboarding", {"summary": "Full profile"})
        assert "APPROVED" in result

    @pytest.mark.asyncio
    async def test_schedule_job_dispatches(self, executor: DirectToolExecutor):
        persona = _make_persona()
        session_fn, mock_db = _mock_async_session(persona)
        mock_count = MagicMock()
        mock_count.scalar.return_value = 0
        mock_db.execute.return_value = mock_count
        future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()

        with (
            patch("app.db.async_session", session_fn),
            patch(
                "app.services.persona_service.get_or_create_persona",
                new_callable=AsyncMock,
                return_value=persona,
            ),
        ):
            result = await executor.dispatch(
                "schedule_job",
                {
                    "name": "Test reminder",
                    "schedule_type": "at",
                    "schedule_value": future,
                    "payload_message": "Check status",
                },
            )
        assert "scheduled" in result.lower() or "error" not in result.lower()

    @pytest.mark.asyncio
    async def test_list_scheduled_jobs_dispatches(self, executor: DirectToolExecutor):
        persona = _make_persona()
        session_fn, mock_db = _mock_async_session(persona)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        with (
            patch("app.db.async_session", session_fn),
            patch(
                "app.services.persona_service.get_or_create_persona",
                new_callable=AsyncMock,
                return_value=persona,
            ),
        ):
            result = await executor.dispatch("list_scheduled_jobs", {})
        assert "No scheduled jobs" in result

    @pytest.mark.asyncio
    async def test_cancel_scheduled_job_dispatches(self, executor: DirectToolExecutor):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        @asynccontextmanager
        async def _session():
            yield mock_db

        with patch("app.db.async_session", _session):
            result = await executor.dispatch(
                "cancel_scheduled_job", {"job_id": "nonexistent"}
            )
        assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_steer_consultation_dispatches(self, executor: DirectToolExecutor):
        mock_result = MagicMock()
        mock_result.content = "Follow-up response."
        mock_result.session_id = "sess-100"

        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=1)
        mock_redis.expire = AsyncMock()
        mock_redis.close = AsyncMock()

        mock_db = AsyncMock()
        mock_persona = _make_persona()
        mock_persona_result = MagicMock()
        mock_persona_result.scalar_one_or_none.return_value = mock_persona
        mock_db.execute.return_value = mock_persona_result

        @asynccontextmanager
        async def _session():
            yield mock_db

        with (
            patch("app.db.async_session", _session),
            patch(
                "app.api.complete.core.complete_internal",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
            patch("redis.asyncio.from_url", return_value=mock_redis),
        ):
            result = await executor.dispatch(
                "steer_consultation",
                {"project_id": "persona-sandbox", "session_id": "sess-100", "message": "follow up"},
            )
        assert "sess-100" in result

    @pytest.mark.asyncio
    async def test_list_consultations_dispatches(self, executor: DirectToolExecutor):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        @asynccontextmanager
        async def _session():
            yield mock_db

        with patch("app.db.async_session", _session):
            result = await executor.dispatch("list_consultations", {})
        assert "No consultations" in result

    @pytest.mark.asyncio
    async def test_cancel_consultation_dispatches(self, executor: DirectToolExecutor):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        @asynccontextmanager
        async def _session():
            yield mock_db

        with patch("app.db.async_session", _session):
            result = await executor.dispatch(
                "cancel_consultation", {"session_id": "nonexistent"}
            )
        assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_manage_tasks_dispatches(self, executor: DirectToolExecutor):
        # manage_tasks requires bash_fn bound via _model_tool_registry
        result = await executor.dispatch("manage_tasks", {"action": "list_ready"})
        # Will attempt real st CLI call — just verify it dispatches without "Unknown tool"
        assert "Unknown tool" not in result

    @pytest.mark.asyncio
    async def test_manage_model_config_dispatches(self, executor: DirectToolExecutor):
        with patch(
            "app.services.tools._executor_model_mgmt.list_models",
            new_callable=AsyncMock,
            return_value="Model catalog...",
        ):
            result = await executor.dispatch(
                "manage_model_config", {"action": "list_models"}
            )
        assert "Model catalog" in result

    @pytest.mark.asyncio
    async def test_log_agent_performance_dispatches(self, executor: DirectToolExecutor):
        mock_log = MagicMock()
        mock_log.id = 42
        mock_log.created_at = datetime.now(UTC)

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()

        async def _refresh(obj: Any) -> None:
            obj.id = 42

        mock_db.refresh = _refresh

        @asynccontextmanager
        async def _session():
            yield mock_db

        with patch("app.db.async_session", _session):
            result = await executor.dispatch(
                "log_agent_performance",
                {
                    "agent_slug": "planner",
                    "model_id": "claude-sonnet-4-5",
                    "feedback_type": "praise",
                    "content": "Excellent planning output.",
                    "outcome": "success",
                },
            )
        assert "Performance logged" in result
        assert "praise" in result

    @pytest.mark.asyncio
    async def test_review_agent_performance_dispatches(self, executor: DirectToolExecutor):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_result.all.return_value = []
        mock_db.execute.return_value = mock_result

        @asynccontextmanager
        async def _session():
            yield mock_db

        with patch("app.db.async_session", _session):
            result = await executor.dispatch("review_agent_performance", {})
        assert "No performance logs" in result

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self, executor: DirectToolExecutor):
        result = await executor.dispatch("nonexistent_tool", {})
        assert "Unknown tool" in result


# ---------------------------------------------------------------------------
# 2. PERSONA-SANDBOX WORKING DIRECTORY
# ---------------------------------------------------------------------------


class TestPersonaSandboxWorkingDir:
    """Verify bash, read_file, write_file work in persona-sandbox context."""

    @pytest.fixture
    def executor(self, tmp_path: Path) -> DirectToolExecutor:
        """Executor rooted in a temporary sandbox dir."""
        return DirectToolExecutor(str(tmp_path), project_id="persona-sandbox")

    @pytest.mark.asyncio
    async def test_bash_runs_in_working_dir(self, executor: DirectToolExecutor):
        result = await executor.dispatch("bash", {"command": "pwd"})
        assert str(executor.working_dir) in result

    @pytest.mark.asyncio
    async def test_write_and_read_file(self, executor: DirectToolExecutor):
        test_file = str(executor.working_dir / "test.txt")
        write_result = await executor.dispatch(
            "write_file", {"path": test_file, "content": "hello from jenny"}
        )
        assert "Error" not in write_result or "wrote" in write_result.lower()

        read_result = await executor.dispatch("read_file", {"path": test_file})
        assert "hello from jenny" in read_result

    @pytest.mark.asyncio
    async def test_bash_echo_works(self, executor: DirectToolExecutor):
        result = await executor.dispatch("bash", {"command": "echo 'sandbox active'"})
        assert "sandbox active" in result

    @pytest.mark.asyncio
    async def test_bash_creates_file(self, executor: DirectToolExecutor):
        test_file = str(executor.working_dir / "created.txt")
        result = await executor.dispatch(
            "bash", {"command": f"echo 'test content' > {test_file} && cat {test_file}"}
        )
        assert "test content" in result

    @pytest.mark.asyncio
    async def test_no_path_restriction_for_sandbox(self, executor: DirectToolExecutor):
        """persona-sandbox is NOT in KNOWN_ROOTS, so has no path boundary."""
        # Reading /tmp should work (no restriction)
        tmp_file = f"/tmp/persona_test_{uuid.uuid4().hex[:8]}.txt"
        write_result = await executor.dispatch(
            "write_file", {"path": tmp_file, "content": "temporary"}
        )
        assert "Error" not in write_result or "wrote" in write_result.lower()
        # Cleanup
        os.unlink(tmp_file) if os.path.exists(tmp_file) else None


# ---------------------------------------------------------------------------
# 3. PERMISSION TIER EXEMPTIONS
# ---------------------------------------------------------------------------


class TestPersonaToolTierExemption:
    """Persona tools bypass project tier checks (except tier=off)."""

    ALL_PERSONA_INTERNAL = [
        "read_personality",
        "write_personality",
        "read_journal",
        "search_journal",
        "write_journal",
        "read_user_context",
        "write_user_context",
        "submit_onboarding",
        "mark_memory_relevant",
        "mark_memory_irrelevant",
        "manage_model_config",
        "log_agent_performance",
        "review_agent_performance",
    ]

    ALL_PERSONA_OPERATIONAL = [
        "manage_tasks",
        "schedule_job",
        "cancel_scheduled_job",
        "send_push",
        "steer_consultation",
        "cancel_consultation",
    ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("tool_name", ALL_PERSONA_INTERNAL + ALL_PERSONA_OPERATIONAL)
    async def test_persona_tools_allowed_at_read_tier(self, tool_name: str):
        """All 19 persona tools should be allowed even when project is at read tier."""
        from app.services.project_permission_service import check_tool_allowed

        mock_db = AsyncMock()
        mock_perm = MagicMock()
        mock_perm.permission_tier = "read"
        mock_perm.auto_exec_enabled = False

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_perm
        mock_db.execute.return_value = mock_result

        @asynccontextmanager
        async def _session():
            yield mock_db

        with (
            patch("app.db.async_session", _session),
            patch(
                "app.services.project_permission_service._get_cached_tier",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            allowed, reason = await check_tool_allowed("persona-sandbox", tool_name, db=mock_db)

        assert allowed is True, f"Tool {tool_name} denied at read tier: {reason}"
        assert "tier-exempt" in reason

    @pytest.mark.asyncio
    @pytest.mark.parametrize("tool_name", ALL_PERSONA_INTERNAL + ALL_PERSONA_OPERATIONAL)
    async def test_persona_tools_denied_at_off_tier(self, tool_name: str):
        """All persona tools should be DENIED when project tier is off."""
        from app.services.project_permission_service import check_tool_allowed

        with patch(
            "app.services.project_permission_service._get_cached_tier",
            new_callable=AsyncMock,
            return_value="off",
        ):
            allowed, reason = await check_tool_allowed("persona-sandbox", tool_name)

        assert allowed is False, f"Tool {tool_name} should be denied at off tier"
        assert "off" in reason

    @pytest.mark.asyncio
    async def test_bash_denied_at_read_tier(self):
        """bash is NOT a persona tool — should be denied at read tier."""
        from app.services.project_permission_service import check_tool_allowed

        with patch(
            "app.services.project_permission_service._get_cached_tier",
            new_callable=AsyncMock,
            return_value="read",
        ):
            allowed, reason = await check_tool_allowed("persona-sandbox", "bash")

        assert allowed is False

    @pytest.mark.asyncio
    async def test_bash_allowed_at_yolo_tier(self):
        """bash allowed at yolo tier."""
        from app.services.project_permission_service import check_tool_allowed

        with patch(
            "app.services.project_permission_service._get_cached_tier",
            new_callable=AsyncMock,
            return_value="yolo",
        ):
            allowed, reason = await check_tool_allowed("persona-sandbox", "bash")

        assert allowed is True


# ---------------------------------------------------------------------------
# 4. TOOL HANDLER PIPELINE (permission hooks → executor)
# ---------------------------------------------------------------------------


class TestToolHandlerPipeline:
    """Verify the full handler pipeline: composed hooks → executor dispatch."""

    @pytest.mark.asyncio
    async def test_handler_allows_persona_tool_at_read_tier(self, tmp_path: Path):
        """Persona tools pass through even when project tier is read."""
        persona = _make_persona(personality="Direct and warm.")
        session_fn, _ = _mock_async_session(persona)

        with (
            patch(
                "app.services.project_permission_service._get_cached_tier",
                new_callable=AsyncMock,
                return_value="read",
            ),
            patch("app.db.async_session", session_fn),
            patch(
                "app.services.persona_service.get_or_create_persona",
                new_callable=AsyncMock,
                return_value=persona,
            ),
        ):
            handler = create_direct_handler(
                working_dir=str(tmp_path), project_id="persona-sandbox"
            )
            call = ToolCall(id="t1", name="read_personality", input={})
            result = await handler.execute(call)

        assert not result.is_error, f"Expected success, got: {result.content}"
        assert "Direct and warm." in result.content

    @pytest.mark.asyncio
    async def test_handler_denies_bash_at_read_tier(self, tmp_path: Path):
        """bash should be denied when project tier is read."""
        with patch(
            "app.services.project_permission_service._get_cached_tier",
            new_callable=AsyncMock,
            return_value="read",
        ):
            handler = create_direct_handler(
                working_dir=str(tmp_path), project_id="persona-sandbox"
            )
            call = ToolCall(id="t2", name="bash", input={"command": "echo test"})
            result = await handler.execute(call)

        assert result.is_error
        assert "denied" in result.content.lower()

    @pytest.mark.asyncio
    async def test_handler_allows_bash_at_yolo_tier(self, tmp_path: Path):
        """bash allowed at yolo tier."""
        with patch(
            "app.services.project_permission_service._get_cached_tier",
            new_callable=AsyncMock,
            return_value="yolo",
        ):
            handler = create_direct_handler(
                working_dir=str(tmp_path), project_id="persona-sandbox"
            )
            call = ToolCall(id="t3", name="bash", input={"command": "echo allowed"})
            result = await handler.execute(call)

        assert not result.is_error
        assert "allowed" in result.content

    @pytest.mark.asyncio
    async def test_handler_denies_everything_at_off_tier(self, tmp_path: Path):
        """All tools denied at off tier, including persona tools."""
        with patch(
            "app.services.project_permission_service._get_cached_tier",
            new_callable=AsyncMock,
            return_value="off",
        ):
            handler = create_direct_handler(
                working_dir=str(tmp_path), project_id="persona-sandbox"
            )

            for tool_name in ["read_personality", "bash", "write_journal"]:
                call = ToolCall(id="t0", name=tool_name, input={})
                result = await handler.execute(call)
                assert result.is_error, f"{tool_name} should be denied at off tier"

    @pytest.mark.asyncio
    async def test_sdk_pascal_case_normalized(self, tmp_path: Path):
        """SDK sends PascalCase (Bash, Read) — handler normalizes to lowercase."""
        with patch(
            "app.services.project_permission_service._get_cached_tier",
            new_callable=AsyncMock,
            return_value="yolo",
        ):
            handler = create_direct_handler(
                working_dir=str(tmp_path), project_id="persona-sandbox"
            )
            call = ToolCall(id="t4", name="Bash", input={"command": "echo normalized"})
            result = await handler.execute(call)

        assert not result.is_error
        assert "normalized" in result.content


# ---------------------------------------------------------------------------
# 5. CROSS-PROJECT PATH ENFORCEMENT
# ---------------------------------------------------------------------------


class TestCrossProjectPathEnforcement:
    """Verify persona-sandbox correctly enforces cross-project file access."""

    @pytest.mark.asyncio
    async def test_cross_project_read_denied_at_off_tier(self):
        """Reading a file in a project with tier=off should be denied."""
        hook = _create_cross_project_permission_hook("persona-sandbox")

        with patch(
            "app.services.project_permission_service._get_cached_tier",
            new_callable=AsyncMock,
            return_value="off",
        ):
            call = ToolCall(
                id="x1",
                name="read_file",
                input={"path": "/home/kasadis/summitflow/src/main.py"},
            )
            decision = await hook(call)

        assert decision == ToolDecision.DENY

    @pytest.mark.asyncio
    async def test_cross_project_read_allowed_at_read_tier(self):
        """Reading a file in a project with tier=read should be allowed."""
        hook = _create_cross_project_permission_hook("persona-sandbox")

        with patch(
            "app.services.project_permission_service._get_cached_tier",
            new_callable=AsyncMock,
            return_value="read",
        ):
            call = ToolCall(
                id="x2",
                name="read_file",
                input={"path": "/home/kasadis/summitflow/src/main.py"},
            )
            decision = await hook(call)

        assert decision == ToolDecision.ALLOW

    @pytest.mark.asyncio
    async def test_cross_project_write_denied_at_read_tier(self):
        """Writing to a project with tier=read should be denied."""
        hook = _create_cross_project_permission_hook("persona-sandbox")

        with patch(
            "app.services.project_permission_service._get_cached_tier",
            new_callable=AsyncMock,
            return_value="read",
        ):
            call = ToolCall(
                id="x3",
                name="write_file",
                input={"path": "/home/kasadis/summitflow/src/main.py", "content": "hack"},
            )
            decision = await hook(call)

        assert decision == ToolDecision.DENY

    @pytest.mark.asyncio
    async def test_cross_project_write_allowed_at_write_tier(self):
        """Writing to a project with tier=write should be allowed."""
        hook = _create_cross_project_permission_hook("persona-sandbox")

        with patch(
            "app.services.project_permission_service._get_cached_tier",
            new_callable=AsyncMock,
            return_value="write",
        ):
            call = ToolCall(
                id="x4",
                name="write_file",
                input={"path": "/home/kasadis/summitflow/src/main.py", "content": "ok"},
            )
            decision = await hook(call)

        assert decision == ToolDecision.ALLOW

    @pytest.mark.asyncio
    async def test_sandbox_local_paths_allowed(self):
        """Files not in any known project root should be allowed."""
        hook = _create_cross_project_permission_hook("persona-sandbox")

        call = ToolCall(
            id="x5",
            name="read_file",
            input={"path": "/tmp/scratch.txt"},
        )
        decision = await hook(call)
        assert decision == ToolDecision.ALLOW

    @pytest.mark.asyncio
    async def test_bash_cross_project_denied_at_read_tier(self):
        """Bash referencing another project's root should be denied at read tier."""
        hook = _create_cross_project_permission_hook("persona-sandbox")

        with patch(
            "app.services.project_permission_service._get_cached_tier",
            new_callable=AsyncMock,
            return_value="read",
        ):
            call = ToolCall(
                id="x6",
                name="bash",
                input={"command": "cat /home/kasadis/summitflow/pyproject.toml"},
            )
            decision = await hook(call)

        assert decision == ToolDecision.DENY

    @pytest.mark.asyncio
    async def test_persona_tools_not_path_gated(self):
        """Persona-specific tools (non-file, non-bash) skip cross-project checks."""
        hook = _create_cross_project_permission_hook("persona-sandbox")

        for tool_name in ["read_personality", "write_journal", "schedule_job"]:
            call = ToolCall(id="x7", name=tool_name, input={})
            decision = await hook(call)
            assert decision == ToolDecision.ALLOW, f"{tool_name} should not be path-gated"


# ---------------------------------------------------------------------------
# 6. HOOK COMPOSITION
# ---------------------------------------------------------------------------


class TestHookComposition:
    """Verify _compose_hooks: first DENY wins, fail-closed on error."""

    @pytest.mark.asyncio
    async def test_all_allow_passes(self):
        async def allow(_: ToolCall) -> ToolDecision:
            return ToolDecision.ALLOW

        composed = _compose_hooks([allow, allow, allow])
        result = await composed(ToolCall(id="h1", name="test", input={}))
        assert result == ToolDecision.ALLOW

    @pytest.mark.asyncio
    async def test_first_deny_wins(self):
        async def allow(_: ToolCall) -> ToolDecision:
            return ToolDecision.ALLOW

        async def deny(_: ToolCall) -> ToolDecision:
            return ToolDecision.DENY

        composed = _compose_hooks([allow, deny, allow])
        result = await composed(ToolCall(id="h2", name="test", input={}))
        assert result == ToolDecision.DENY

    @pytest.mark.asyncio
    async def test_exception_fails_closed(self):
        async def explode(_: ToolCall) -> ToolDecision:
            raise RuntimeError("boom")

        composed = _compose_hooks([explode])
        result = await composed(ToolCall(id="h3", name="test", input={}))
        assert result == ToolDecision.DENY


# ---------------------------------------------------------------------------
# 7. DISPATCHABLE_TOOLS COMPLETENESS
# ---------------------------------------------------------------------------


class TestDispatchableToolsComplete:
    """Ensure DISPATCHABLE_TOOLS contains all persona tools."""

    def test_all_persona_tools_in_dispatchable_set(self):
        """Every tool in PERSONA_EXTRA_TOOLS should be in DISPATCHABLE_TOOLS."""
        from app.services.tools._persona_tools import PERSONA_EXTRA_TOOLS

        dispatchable = DirectToolExecutor.DISPATCHABLE_TOOLS
        for tool in PERSONA_EXTRA_TOOLS:
            assert tool.name in dispatchable, (
                f"Tool '{tool.name}' from PERSONA_EXTRA_TOOLS "
                f"missing from DISPATCHABLE_TOOLS"
            )

    def test_persona_permission_sets_cover_tools(self):
        """All persona tools should be reachable (either tier-exempt or in standard tiers)."""
        from app.services.project_permission_service import (
            _PERSONA_TOOLS,
            TIER_TOOLS,
        )
        from app.services.tools._persona_tools import PERSONA_EXTRA_TOOLS

        tool_names = {t.name for t in PERSONA_EXTRA_TOOLS}
        # Every persona tool should be either in _PERSONA_TOOLS (tier-exempt)
        # or available in the yolo tier (standard tools)
        yolo_tools = TIER_TOOLS["yolo"]
        for name in tool_names:
            assert name in _PERSONA_TOOLS or name in yolo_tools, (
                f"Tool '{name}' not reachable — missing from both "
                f"_PERSONA_TOOLS exemption set and yolo tier"
            )

    def test_send_push_in_dispatchable(self):
        """send_push is registered via _model_tool_registry, verify it's dispatchable."""
        assert "send_push" in DirectToolExecutor.DISPATCHABLE_TOOLS


# ---------------------------------------------------------------------------
# 8. PROVIDER INTEGRATION (Claude + Gemini) — requires --run-integration
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestProviderIntegration:
    """Live tests against Claude and Gemini providers with persona agent.

    These tests require running services and --run-integration flag.
    Gemini CloudCode rate-limits at ~1-2 req/min, so tests are minimal.
    """

    @pytest.mark.asyncio
    async def test_claude_completion_with_persona(self):
        """Claude provider returns a valid completion for the persona agent."""
        import httpx

        async with httpx.AsyncClient(base_url="http://localhost:8003") as client:
            response = await client.post(
                "/api/complete",
                json={
                    "messages": [{"role": "user", "content": "Say 'hello' and nothing else."}],
                    "agent_slug": "persona",
                    "project_id": "persona-sandbox",
                    "provider": "claude",
                    "model": "claude-haiku-4-5",
                    "temperature": 0.1,
                    "max_turns": 1,
                    "execute_tools": False,
                },
                headers={
                    "X-Source-Client": "pytest-integration",
                    "X-Source-Path": "/tests/persona",
                    "X-Agent-Hub-Internal": "agent-hub-internal-v1",
                },
                timeout=30.0,
            )
            assert response.status_code == 200, f"Claude failed: {response.text}"
            data = response.json()
            assert "content" in data
            assert len(data["content"]) > 0

    @pytest.mark.asyncio
    async def test_gemini_completion_with_persona(self):
        """Gemini provider returns a valid completion for the persona agent.

        Note: Gemini CloudCode rate-limits at ~1-2 req/min.
        """
        import asyncio

        import httpx

        # Small delay to respect rate limits
        await asyncio.sleep(2)

        async with httpx.AsyncClient(base_url="http://localhost:8003") as client:
            response = await client.post(
                "/api/complete",
                json={
                    "messages": [{"role": "user", "content": "Say 'hello' and nothing else."}],
                    "agent_slug": "persona",
                    "project_id": "persona-sandbox",
                    "provider": "gemini",
                    "model": "gemini-2.0-flash",
                    "temperature": 0.1,
                    "max_turns": 1,
                    "execute_tools": False,
                },
                headers={
                    "X-Source-Client": "pytest-integration",
                    "X-Source-Path": "/tests/persona",
                    "X-Agent-Hub-Internal": "agent-hub-internal-v1",
                },
                timeout=30.0,
            )
            assert response.status_code == 200, f"Gemini failed: {response.text}"
            data = response.json()
            assert "content" in data
            assert len(data["content"]) > 0

    @pytest.mark.asyncio
    async def test_persona_tool_execution_via_api(self):
        """Persona agent can execute tools via the completion API."""
        import httpx

        async with httpx.AsyncClient(base_url="http://localhost:8003") as client:
            response = await client.post(
                "/api/complete",
                json={
                    "messages": [
                        {
                            "role": "user",
                            "content": (
                                "Call the read_personality tool to read your personality "
                                "document. Report what it says."
                            ),
                        }
                    ],
                    "agent_slug": "persona",
                    "project_id": "persona-sandbox",
                    "provider": "claude",
                    "model": "claude-haiku-4-5",
                    "temperature": 0.1,
                    "max_turns": 3,
                    "execute_tools": True,
                },
                headers={
                    "X-Source-Client": "pytest-integration",
                    "X-Source-Path": "/tests/persona",
                    "X-Agent-Hub-Internal": "agent-hub-internal-v1",
                },
                timeout=60.0,
            )
            assert response.status_code == 200, f"Tool execution failed: {response.text}"
            data = response.json()
            assert "content" in data
            # The response should contain personality info since the tool was executed
            assert len(data["content"]) > 20
