"""Integration tests for the persona agent — tools, permissions, sandbox, and providers.

Verifies the full persona pipeline is functional:
1. All persona tools dispatch correctly via DirectToolExecutor
2. Persona-sandbox working directory (bash, read_file, write_file)
3. Permission tier exemptions (persona tools bypass project tier)
4. Permission DENY at tier=off
5. Cross-project path enforcement from persona-sandbox
6. Tool handler → executor pipeline with composed permission hooks
"""

from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.models import CLAUDE_SONNET
from app.models.persona import Persona
from app.services.tools._persona_tools import PERSONA_EXTRA_TOOLS
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

SANDBOX_DIR = "/home/testuser/persona-sandbox"


@pytest.fixture(autouse=True)
def allow_test_bash_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    """Allow real bash execution where the SummitFlow shared guard is absent (CI)."""
    monkeypatch.setattr(
        "app.services.tools._executor_bash.get_command_guard_block_reason",
        lambda *_args, **_kwargs: None,
    )


def _make_persona(**overrides: Any) -> MagicMock:
    """Create a mock Persona with sensible defaults."""
    defaults = {
        "id": 1,
        "agent_id": 10,
        "name": "Persona",
        "personality": "I'm a helpful assistant.",
        "user_context": "User prefers concise answers.",
        "voice_id": "en-AU-NatashaNeural",
        "voice_enabled": False,
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


def _mock_async_session(persona: Any):
    """Create a mock async_session context manager."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = persona
    mock_result.scalars.return_value.all.return_value = []
    mock_result.scalar.return_value = 0
    mock_db.execute.return_value = mock_result
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()

    @asynccontextmanager
    async def _session():
        yield mock_db

    return _session, mock_db


@pytest.fixture(autouse=True)
def _mock_prompt_backed_persona_documents():
    async def _get_personality(db):
        result = await db.execute(object())
        persona = result.scalar_one_or_none()
        if persona is None:
            return None
        return getattr(persona, "personality", None)

    async def _set_personality(db, personality, **_kwargs):
        result = await db.execute(object())
        persona = result.scalar_one_or_none()
        old_text = (getattr(persona, "personality", "") or "").strip()
        persona.personality = personality.strip()
        return len(old_text), len(persona.personality)

    async def _get_user_context(db):
        result = await db.execute(object())
        persona = result.scalar_one_or_none()
        if persona is None:
            return None
        return getattr(persona, "user_context", None)

    async def _set_user_context(db, user_context, **_kwargs):
        result = await db.execute(object())
        persona = result.scalar_one_or_none()
        old_text = (getattr(persona, "user_context", "") or "").strip()
        persona.user_context = user_context.strip()
        return len(old_text), len(persona.user_context)

    with (
        patch(
            "app.services.persona_document_prompt_service.get_persona_personality_document",
            new=_get_personality,
        ),
        patch(
            "app.services.persona_document_prompt_service.set_persona_personality_document",
            new=_set_personality,
        ),
        patch(
            "app.services.persona_document_prompt_service.get_persona_user_context_document",
            new=_get_user_context,
        ),
        patch(
            "app.services.persona_document_prompt_service.set_persona_user_context_document",
            new=_set_user_context,
        ),
    ):
        yield


# ---------------------------------------------------------------------------
# 1. EVERY PERSONA TOOL DISPATCHES VIA EXECUTOR
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tool_name",
    [tool.name for tool in PERSONA_EXTRA_TOOLS],
)
@pytest.mark.asyncio
async def test_every_persona_extra_tool_dispatches(tmp_path: Path, tool_name: str):
    """Every PERSONA_EXTRA_TOOLS entry routes through DirectToolExecutor.dispatch()."""
    executor = DirectToolExecutor(str(tmp_path), project_id="persona-sandbox")
    handler = AsyncMock(return_value=f"handled {tool_name}")
    if tool_name in executor._registry:
        executor._registry[tool_name] = handler
    else:
        setattr(executor, tool_name, handler)

    result = await executor.dispatch(tool_name, {})

    assert result == f"handled {tool_name}"
    handler.assert_awaited_once()


class TestPersonaBashWorkflowGuards:
    """Verify persona workflow restrictions in Bash execution."""

    @pytest.fixture
    def executor(self, tmp_path: Path) -> DirectToolExecutor:
        return DirectToolExecutor(str(tmp_path), project_id="persona-sandbox")

    @pytest.mark.asyncio
    async def test_persona_bash_blocks_raw_git_commit(self, tmp_path: Path):
        executor = DirectToolExecutor(str(tmp_path), project_id="agent-hub", agent_slug="persona")

        result = await executor.dispatch(
            "bash",
            {"command": "git commit -m 'test'"},
        )

        assert "blocked for workflow policy" in result.lower()
        assert "commit.sh" in result

    @pytest.mark.asyncio
    async def test_persona_bash_blocks_raw_git_push(self, tmp_path: Path):
        executor = DirectToolExecutor(str(tmp_path), project_id="agent-hub", agent_slug="persona")

        result = await executor.dispatch(
            "bash",
            {"command": "git push origin main"},
        )

        assert "blocked for workflow policy" in result.lower()
        assert "commit.sh" in result

    @pytest.mark.asyncio
    async def test_non_persona_bash_does_not_block_git_commit(self, tmp_path: Path):
        executor = DirectToolExecutor(str(tmp_path), project_id="agent-hub", agent_slug="coder")

        result = await executor.dispatch(
            "bash",
            {"command": "git commit -m 'test'"},
        )

        assert "blocked for workflow policy" not in result.lower()

    @pytest.mark.asyncio
    async def test_manage_tasks_dispatches(self, tmp_path: Path):
        # manage_tasks is bound to the executor's bash at registry build time.
        fake_bash = AsyncMock(return_value="st overview output")
        with patch.object(DirectToolExecutor, "bash", fake_bash):
            executor = DirectToolExecutor(str(tmp_path), project_id="persona-sandbox")
            result = await executor.dispatch("manage_tasks", {"action": "overview"})
        assert "Unknown tool" not in result
        fake_bash.assert_awaited()
        assert any("st " in str(call.args[0]) for call in fake_bash.await_args_list)

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
    async def test_manage_model_config_update_agent_memory_dispatches(self, executor: DirectToolExecutor):
        with patch(
            "app.services.tools._executor_model_mgmt.update_agent_memory",
            new_callable=AsyncMock,
            return_value="Agent 'persona' memory updated (version 8).",
        ):
            result = await executor.dispatch(
                "manage_model_config",
                {
                    "action": "update_agent_memory",
                    "agent_slug": "persona",
                    "memory_config_patch": {"include_references": True},
                    "add_audience_tags": ["persona-relevant"],
                    "change_reason": "route references",
                },
            )
        assert "memory updated" in result

    @pytest.mark.asyncio
    async def test_log_agent_performance_dispatches(self, executor: DirectToolExecutor):
        mock_log = MagicMock()
        mock_log.id = 42
        mock_log.created_at = datetime.now(UTC)

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()

        # Dedup check: scalar_one_or_none must return None (no recent log)
        mock_dedup_result = MagicMock()
        mock_dedup_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_dedup_result

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
                    "model_id": CLAUDE_SONNET,
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
            "write_file", {"path": test_file, "content": "hello from persona"}
        )
        assert "Error" not in write_result or "wrote" in write_result.lower()

        read_result = await executor.dispatch("read_file", {"path": test_file})
        assert "hello from persona" in read_result

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

    ALL_PERSONA_INTERNAL: ClassVar[list[str]] = [
        "read_personality",
        "write_personality",
        "read_user_context",
        "write_user_context",
        "submit_onboarding",
        "mark_memory_relevant",
        "mark_memory_irrelevant",
        "manage_model_config",
        "log_agent_performance",
        "review_agent_performance",
    ]

    SAFE_PERSONA_OPERATIONAL: ClassVar[list[str]] = [
        "steer_consultation",
        "cancel_consultation",
        "query_sessions",
        "inspect_session",
    ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("tool_name", ALL_PERSONA_INTERNAL + SAFE_PERSONA_OPERATIONAL)
    async def test_persona_tools_allowed_at_read_tier(self, tool_name: str):
        """All persona tools should be allowed even when project is at read tier."""
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
    async def test_manage_tasks_overview_denied_at_read_tier(self):
        from app.services.project_permission_service import check_tool_allowed

        with patch(
            "app.services.project_permission_service._get_cached_tier",
            new_callable=AsyncMock,
            return_value="read",
        ):
            allowed, reason = await check_tool_allowed(
                "persona-sandbox",
                "manage_tasks",
                tool_input={"action": "overview"},
            )

        assert allowed is False
        assert "direct helper tool disabled" in reason

    @pytest.mark.asyncio
    async def test_manage_tasks_dispatch_denied_at_read_tier(self):
        from app.services.project_permission_service import check_tool_allowed

        with patch(
            "app.services.project_permission_service._get_cached_tier",
            new_callable=AsyncMock,
            return_value="read",
        ):
            allowed, reason = await check_tool_allowed(
                "persona-sandbox",
                "manage_tasks",
                tool_input={"action": "dispatch"},
            )

        assert allowed is False
        assert "direct helper tool disabled" in reason

    @pytest.mark.asyncio
    async def test_dispatch_agent_denied_at_read_tier(self):
        from app.services.project_permission_service import check_tool_allowed

        with patch(
            "app.services.project_permission_service._get_cached_tier",
            new_callable=AsyncMock,
            return_value="read",
        ):
            allowed, reason = await check_tool_allowed("persona-sandbox", "dispatch_agent")

        assert allowed is False
        assert "direct helper tool disabled" in reason

    @pytest.mark.asyncio
    @pytest.mark.parametrize("tool_name", ALL_PERSONA_INTERNAL + SAFE_PERSONA_OPERATIONAL + ["manage_tasks", "dispatch_agent"])
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
            allowed, _reason = await check_tool_allowed("persona-sandbox", "bash")

        assert allowed is False

    @pytest.mark.asyncio
    async def test_bash_allowed_at_full_tier(self):
        """bash allowed at full tier."""
        from app.services.project_permission_service import check_tool_allowed

        with patch(
            "app.services.project_permission_service._get_cached_tier",
            new_callable=AsyncMock,
            return_value="full",
        ):
            allowed, _reason = await check_tool_allowed("persona-sandbox", "bash")

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
    async def test_handler_allows_bash_at_full_tier(self, tmp_path: Path):
        """bash allowed at full tier."""
        with patch(
            "app.services.project_permission_service._get_cached_tier",
            new_callable=AsyncMock,
            return_value="full",
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

            for tool_name in ["read_personality", "bash"]:
                call = ToolCall(id="t0", name=tool_name, input={})
                result = await handler.execute(call)
                assert result.is_error, f"{tool_name} should be denied at off tier"

    @pytest.mark.asyncio
    async def test_sdk_pascal_case_normalized(self, tmp_path: Path):
        """SDK sends PascalCase (Bash, Read) — handler normalizes to lowercase."""
        with patch(
            "app.services.project_permission_service._get_cached_tier",
            new_callable=AsyncMock,
            return_value="full",
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
        with patch(
            "app.services.tools.direct_executor_core.KNOWN_ROOTS",
            {"summitflow": "/home/testuser/summitflow", "persona-sandbox": SANDBOX_DIR},
        ):
            hook = _create_cross_project_permission_hook("persona-sandbox")

            with patch(
                "app.services.project_permission_service._get_cached_tier",
                new_callable=AsyncMock,
                return_value="off",
            ):
                call = ToolCall(
                    id="x1",
                    name="read_file",
                    input={"path": "/home/testuser/summitflow/src/main.py"},
                )
                decision = await hook(call)

        assert decision == ToolDecision.DENY

    @pytest.mark.asyncio
    async def test_cross_project_read_allowed_at_read_tier(self):
        """Reading a file in a project with tier=read should be allowed."""
        with patch(
            "app.services.tools.direct_executor_core.KNOWN_ROOTS",
            {"summitflow": "/home/testuser/summitflow", "persona-sandbox": SANDBOX_DIR},
        ):
            hook = _create_cross_project_permission_hook("persona-sandbox")

            with patch(
                "app.services.project_permission_service._get_cached_tier",
                new_callable=AsyncMock,
                return_value="read",
            ):
                call = ToolCall(
                    id="x2",
                    name="read_file",
                    input={"path": "/home/testuser/summitflow/src/main.py"},
                )
                decision = await hook(call)

        assert decision == ToolDecision.ALLOW

    @pytest.mark.asyncio
    async def test_cross_project_write_denied_at_read_tier(self):
        """Writing to a project with tier=read should be denied."""
        with patch(
            "app.services.tools.direct_executor_core.KNOWN_ROOTS",
            {"summitflow": "/home/testuser/summitflow", "persona-sandbox": SANDBOX_DIR},
        ):
            hook = _create_cross_project_permission_hook("persona-sandbox")

            with patch(
                "app.services.project_permission_service._get_cached_tier",
                new_callable=AsyncMock,
                return_value="read",
            ):
                call = ToolCall(
                    id="x3",
                    name="write_file",
                    input={"path": "/home/testuser/summitflow/src/main.py", "content": "hack"},
                )
                decision = await hook(call)

        assert decision == ToolDecision.DENY

    @pytest.mark.asyncio
    async def test_cross_project_write_allowed_at_write_tier(self):
        """Writing to a project with tier=write should be allowed."""
        with patch(
            "app.services.tools.direct_executor_core.KNOWN_ROOTS",
            {"summitflow": "/home/testuser/summitflow", "persona-sandbox": SANDBOX_DIR},
        ):
            hook = _create_cross_project_permission_hook("persona-sandbox")

            with patch(
                "app.services.project_permission_service._get_cached_tier",
                new_callable=AsyncMock,
                return_value="write",
            ):
                call = ToolCall(
                    id="x4",
                    name="write_file",
                    input={"path": "/home/testuser/summitflow/src/main.py", "content": "ok"},
                )
                decision = await hook(call)

        assert decision == ToolDecision.ALLOW

    @pytest.mark.asyncio
    async def test_sandbox_local_paths_allowed(self):
        """Files not in any known project root should be allowed."""
        with patch(
            "app.services.tools.direct_executor_core.KNOWN_ROOTS",
            {"summitflow": "/home/testuser/summitflow", "persona-sandbox": SANDBOX_DIR},
        ):
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
        with patch(
            "app.services.tools.direct_executor_core.KNOWN_ROOTS",
            {"summitflow": "/home/testuser/summitflow", "persona-sandbox": SANDBOX_DIR},
        ):
            hook = _create_cross_project_permission_hook("persona-sandbox")

            with patch(
                "app.services.project_permission_service._get_cached_tier",
                new_callable=AsyncMock,
                return_value="read",
            ):
                call = ToolCall(
                    id="x6",
                    name="bash",
                    input={"command": "cat /home/testuser/summitflow/pyproject.toml"},
                )
                decision = await hook(call)

        assert decision == ToolDecision.DENY

    @pytest.mark.asyncio
    async def test_cross_project_read_checkout_denied_at_off_tier(self, tmp_path: Path):
        """Reading a file from another project's checkout should honor that project's tier."""
        main_repo = tmp_path / "summitflow"
        main_repo.mkdir()
        (main_repo / ".git" / "checkouts" / "task-123").mkdir(parents=True)

        checkout = tmp_path / "checkouts" / "task-123"
        checkout.mkdir(parents=True)
        (checkout / ".git").write_text(f"gitdir: {main_repo / '.git' / 'checkouts' / 'task-123'}\n")
        target_file = checkout / "backend" / "app.py"
        target_file.parent.mkdir(parents=True)
        target_file.write_text("x = 1\n")

        with patch(
            "app.services.tools.direct_executor_core.KNOWN_ROOTS",
            {"summitflow": str(main_repo), "persona-sandbox": SANDBOX_DIR},
        ):
            hook = _create_cross_project_permission_hook("persona-sandbox")
            with patch(
                "app.services.project_permission_service._get_cached_tier",
                new_callable=AsyncMock,
                return_value="off",
            ):
                call = ToolCall(id="x6b", name="read_file", input={"path": str(target_file)})
                decision = await hook(call)

        assert decision == ToolDecision.DENY

    @pytest.mark.asyncio
    async def test_bash_same_project_checkout_allowed(self, tmp_path: Path):
        """Bash should allow a session project to operate inside its own checkout."""
        main_repo = tmp_path / "summitflow"
        main_repo.mkdir()
        (main_repo / ".git" / "checkouts" / "task-123").mkdir(parents=True)

        checkout = tmp_path / "checkouts" / "task-123"
        checkout.mkdir(parents=True)
        (checkout / ".git").write_text(f"gitdir: {main_repo / '.git' / 'checkouts' / 'task-123'}\n")

        with patch(
            "app.services.tools.direct_executor_core.KNOWN_ROOTS",
            {"summitflow": str(main_repo), "agent-hub": str(tmp_path / "agent-hub")},
        ):
            hook = _create_cross_project_permission_hook("summitflow")
            call = ToolCall(
                id="x6c",
                name="bash",
                input={"command": f"cd {checkout} && git status --short"},
            )
            decision = await hook(call)

        assert decision == ToolDecision.ALLOW

    @pytest.mark.asyncio
    async def test_bash_same_project_checkout_allowed_with_broader_root_present(self, tmp_path: Path):
        """More-specific project roots should win over broader parent roots."""
        main_repo = tmp_path / "summitflow"
        main_repo.mkdir()
        (main_repo / ".git" / "checkouts" / "task-123").mkdir(parents=True)

        checkout = tmp_path / "checkouts" / "task-123"
        checkout.mkdir(parents=True)
        (checkout / ".git").write_text(f"gitdir: {main_repo / '.git' / 'checkouts' / 'task-123'}\n")

        with patch(
            "app.services.tools.direct_executor_core.KNOWN_ROOTS",
            {"st-cli": str(tmp_path), "summitflow": str(main_repo)},
        ):
            hook = _create_cross_project_permission_hook("summitflow")
            call = ToolCall(
                id="x6c2",
                name="bash",
                input={"command": f"cd {checkout} && git status --short"},
            )
            decision = await hook(call)

        assert decision == ToolDecision.ALLOW

    @pytest.mark.asyncio
    async def test_bash_cross_project_checkout_denied_at_read_tier(self, tmp_path: Path):
        """Bash should deny another project's checkout when that target is read-only."""
        summitflow = tmp_path / "summitflow"
        summitflow.mkdir()
        (summitflow / ".git" / "checkouts" / "task-123").mkdir(parents=True)

        checkout = tmp_path / "checkouts" / "task-123"
        checkout.mkdir(parents=True)
        (checkout / ".git").write_text(f"gitdir: {summitflow / '.git' / 'checkouts' / 'task-123'}\n")

        with patch(
            "app.services.tools.direct_executor_core.KNOWN_ROOTS",
            {"summitflow": str(summitflow), "agent-hub": str(tmp_path / "agent-hub")},
        ):
            hook = _create_cross_project_permission_hook("agent-hub")
            with patch(
                "app.services.project_permission_service._get_cached_tier",
                new_callable=AsyncMock,
                return_value="read",
            ):
                call = ToolCall(
                    id="x6d",
                    name="bash",
                    input={"command": f"cd {checkout} && git status --short"},
                )
                decision = await hook(call)

        assert decision == ToolDecision.DENY

    @pytest.mark.asyncio
    async def test_persona_tools_not_path_gated(self):
        """Persona-specific tools (non-file, non-bash) skip cross-project checks."""
        hook = _create_cross_project_permission_hook("persona-sandbox")

        for tool_name in ["read_personality", "steer_consultation"]:
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

    def test_persona_permission_sets_cover_tools(self):
        """All persona tools should be reachable (either tier-exempt or in standard tiers)."""
        from app.services.project_permission_service import (
            _PERSONA_TOOLS,
            TIER_TOOLS,
        )
        from app.services.tools._persona_tools import PERSONA_EXTRA_TOOLS

        tool_names = {t.name for t in PERSONA_EXTRA_TOOLS}
        # Every persona tool should be either in _PERSONA_TOOLS (tier-exempt)
        # or available in the full tier (standard tools)
        full_tools = TIER_TOOLS["full"]
        for name in tool_names:
            assert name in _PERSONA_TOOLS or name in full_tools, (
                f"Tool '{name}' not reachable — missing from both "
                f"_PERSONA_TOOLS exemption set and full tier"
            )

