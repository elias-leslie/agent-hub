"""Tests for direct tool executor."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.tools._executor_file_io import _is_path_allowed
from app.services.tools.base import ToolCall
from app.services.tools.direct_executor import (
    DirectToolExecutor,
    DirectToolHandler,
    _is_blocked_command,
    create_direct_handler,
    get_standard_tools,
)


class TestBlockedCommands:
    """Tests for command blocking."""

    def test_blocks_rm_rf_root(self) -> None:
        """Test that rm -rf / is blocked."""
        assert _is_blocked_command("rm -rf /") is True

    def test_allows_rm_in_directory(self) -> None:
        """Test that rm in a specific directory is allowed."""
        assert _is_blocked_command("rm -rf ./build") is False

    def test_blocks_mkfs(self) -> None:
        """Test that mkfs is blocked."""
        assert _is_blocked_command("mkfs.ext4 /dev/sda1") is True


class TestDirectToolExecutor:
    """Tests for DirectToolExecutor."""

    @pytest.fixture
    def executor(self, tmp_path: Path) -> DirectToolExecutor:
        """Create executor with temp directory."""
        return DirectToolExecutor(str(tmp_path))

    @pytest.mark.asyncio
    async def test_bash_echo(self, executor: DirectToolExecutor) -> None:
        """Test basic bash command."""
        result = await executor.bash("echo hello")
        assert "hello" in result

    @pytest.mark.asyncio
    async def test_bash_inherits_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that bash inherits environment variables."""
        monkeypatch.setenv("TEST_VAR_DIRECT", "test_value_123")
        executor = DirectToolExecutor(str(tmp_path))
        result = await executor.bash("echo $TEST_VAR_DIRECT")
        assert "test_value_123" in result

    @pytest.mark.asyncio
    async def test_bash_blocked_command(self, executor: DirectToolExecutor) -> None:
        """Test that dangerous commands are blocked."""
        result = await executor.bash("rm -rf /")
        assert "blocked" in result.lower()

    @pytest.mark.asyncio
    async def test_bash_uses_working_dir(self, executor: DirectToolExecutor, tmp_path: Path) -> None:
        """Test that bash runs in the correct working directory."""
        result = await executor.bash("pwd")
        assert str(tmp_path) in result

    @pytest.mark.asyncio
    async def test_read_file_success(self, executor: DirectToolExecutor, tmp_path: Path) -> None:
        """Test reading a file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("line1\nline2\nline3")

        result = await executor.read_file("test.txt")
        assert "line1" in result
        assert "line2" in result

    @pytest.mark.asyncio
    async def test_read_file_absolute_path(self, executor: DirectToolExecutor, tmp_path: Path) -> None:
        """Test reading a file with absolute path."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("absolute content")

        result = await executor.read_file(str(test_file))
        assert "absolute content" in result

    @pytest.mark.asyncio
    async def test_read_file_not_found(self, executor: DirectToolExecutor) -> None:
        """Test reading non-existent file."""
        result = await executor.read_file("nonexistent.txt")
        assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_write_file_success(self, executor: DirectToolExecutor, tmp_path: Path) -> None:
        """Test writing a file."""
        result = await executor.write_file("output.txt", "test content")
        assert "successfully" in result.lower()

        written_file = tmp_path / "output.txt"
        assert written_file.exists()
        assert written_file.read_text() == "test content"

    @pytest.mark.asyncio
    async def test_write_file_creates_dirs(self, executor: DirectToolExecutor, tmp_path: Path) -> None:
        """Test that write creates parent directories."""
        result = await executor.write_file("subdir/nested/file.txt", "nested content")
        assert "successfully" in result.lower()

        written_file = tmp_path / "subdir" / "nested" / "file.txt"
        assert written_file.exists()


class TestDirectToolHandler:
    """Tests for DirectToolHandler."""

    @pytest.fixture
    def handler(self, tmp_path: Path) -> DirectToolHandler:
        """Create handler with temp directory."""
        return DirectToolHandler(str(tmp_path))

    @pytest.mark.asyncio
    async def test_execute_bash(self, handler: DirectToolHandler) -> None:
        """Test bash tool via handler."""
        call = ToolCall(id="test-1", name="bash", input={"command": "echo test"})
        result = await handler.execute(call)
        assert not result.is_error
        assert "test" in result.content

    @pytest.mark.asyncio
    async def test_execute_unknown_tool(self, handler: DirectToolHandler) -> None:
        """Test unknown tool returns error."""
        call = ToolCall(id="test-1", name="unknown_tool", input={})
        result = await handler.execute(call)
        assert "unknown" in result.content.lower()


class TestStandardTools:
    """Tests for standard tool definitions."""

    def test_get_standard_tools_returns_all(self) -> None:
        """Test that standard tools include the shared baseline toolset."""
        tools = get_standard_tools()
        names = [t.name for t in tools]
        assert "bash" in names
        assert "read_file" in names
        assert "write_file" in names
        assert "consult_agent" in names
        assert "precision_code_search" in names

    def test_consult_agent_description_prefers_direct_sources_for_exact_facts(self) -> None:
        """Consultation should be framed as advice, not a shortcut around direct lookup."""
        tools = {tool.name: tool for tool in get_standard_tools()}
        consult_tool = tools["consult_agent"]

        assert "expert review" in consult_tool.description
        assert "Do not use it for exact rule text" in consult_tool.description
        assert "`st memory get/search`" in consult_tool.description
        assert consult_tool.usage_examples == [
            "Ask the reviewer agent for risk-focused feedback after inspecting the code.",
        ]

    def test_create_handler_with_workdir(self, tmp_path: Path) -> None:
        """Test handler creation with working directory."""
        handler = create_direct_handler(str(tmp_path))
        assert handler is not None
        assert handler._executor.working_dir == tmp_path

    def test_create_handler_with_project_id(self, tmp_path: Path) -> None:
        """Test handler creation passes project_id to executor."""
        handler = create_direct_handler(str(tmp_path), project_id="test-project")
        assert handler._executor._project_id == "test-project"


class TestDispatch:
    """Tests for the generic dispatch method."""

    @pytest.fixture
    def executor(self, tmp_path: Path) -> DirectToolExecutor:
        return DirectToolExecutor(str(tmp_path))

    @pytest.mark.asyncio
    async def test_dispatch_bash(self, executor: DirectToolExecutor) -> None:
        result = await executor.dispatch("bash", {"command": "echo dispatched"})
        assert "dispatched" in result

    @pytest.mark.asyncio
    async def test_dispatch_unknown_tool(self, executor: DirectToolExecutor) -> None:
        result = await executor.dispatch("nonexistent", {})
        assert "Unknown tool" in result

    @pytest.mark.asyncio
    async def test_dispatch_ignores_extra_args(self, executor: DirectToolExecutor) -> None:
        result = await executor.dispatch("bash", {"command": "echo ok", "bogus": "ignored"})
        assert "ok" in result

    @pytest.mark.asyncio
    async def test_dispatch_read_file(self, executor: DirectToolExecutor, tmp_path: Path) -> None:
        (tmp_path / "test.txt").write_text("dispatch content")
        result = await executor.dispatch("read_file", {"path": "test.txt"})
        assert "dispatch content" in result

    @pytest.mark.asyncio
    async def test_dispatch_precision_code_search(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        executor = DirectToolExecutor(str(tmp_path), project_id="summitflow")
        script_path = tmp_path / "precision-code-search.py"
        script_path.write_text("#!/usr/bin/env python3\n")
        monkeypatch.setattr(
            "app.services.tools._executor_precision_code_search.PRECISION_SEARCH_SCRIPT",
            script_path,
        )

        with patch(
            "app.services.tools._executor_precision_code_search.subprocess.run",
            return_value=SimpleNamespace(
                returncode=0,
                stdout='{"prompt_context":"context","metadata":{"symbol_count":1}}',
                stderr="",
            ),
        ) as mock_run:
            result = await executor.dispatch(
                "precision_code_search",
                {"query": "get_file_tree", "budget": 900},
            )

        assert '"prompt_context": "context"' in result
        cmd = mock_run.call_args.args[0]
        assert cmd[2:7] == ["search", "--project", "summitflow", "--budget", "900"]

    @pytest.mark.asyncio
    async def test_dispatch_precision_code_search_requires_project_context(
        self,
        executor: DirectToolExecutor,
    ) -> None:
        result = await executor.dispatch(
            "precision_code_search",
            {"query": "get_file_tree"},
        )
        assert "project_id context" in result


class TestConsultAgent:
    """Tests for consult_agent tool."""

    @pytest.mark.asyncio
    async def test_consult_agent_no_project_id(self, tmp_path: Path) -> None:
        """Test consult_agent returns error when project_id not set."""
        executor = DirectToolExecutor(str(tmp_path))
        result = await executor.consult_agent("supervisor", "How do I fix this?")
        assert "error" in result.lower()
        assert "project_id" in result.lower()

    @pytest.mark.asyncio
    async def test_consult_agent_handler_dispatch(self, tmp_path: Path) -> None:
        """Test that handler dispatches consult_agent to executor."""
        handler = DirectToolHandler(str(tmp_path))
        call = ToolCall(
            id="test-consult",
            name="consult_agent",
            input={"agent_slug": "supervisor", "question": "Help me"},
        )
        result = await handler.execute(call)
        assert "project_id" in result.content.lower()

    @pytest.mark.asyncio
    async def test_dispatch_agent_includes_parent_session_id(self, tmp_path: Path) -> None:
        """Dispatched child sessions should link back to the current session."""
        executor = DirectToolExecutor(
            str(tmp_path),
            project_id="summitflow",
            session_id="parent-session-789",
        )
        with patch(
            "app.services.tools._executor_consultation.dispatch_agent",
            new_callable=AsyncMock,
            return_value="ok",
        ) as mock_dispatch:
            await executor.dispatch_agent("debugger", "Advance stale state recovery")

        mock_dispatch.assert_awaited_once_with(
            "summitflow",
            "debugger",
            "Advance stale state recovery",
            25,
            parent_session_id="parent-session-789",
        )


class TestPathAllowedWithExtraRoots:
    """Tests for _is_path_allowed with extra_roots (worktree support)."""

    def test_path_within_allowed_root(self, tmp_path: Path) -> None:
        """Path inside allowed_root passes."""
        file_path = tmp_path / "src" / "main.py"
        assert _is_path_allowed(file_path, tmp_path) is True

    def test_path_outside_allowed_root_denied(self, tmp_path: Path) -> None:
        """Path outside allowed_root and no extra_roots is denied."""
        external = Path("/tmp/other-project/file.py")
        assert _is_path_allowed(external, tmp_path) is False

    def test_path_in_extra_root_allowed(self, tmp_path: Path) -> None:
        """Path outside allowed_root but inside extra_roots is allowed (worktree)."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        worktree = tmp_path / "worktrees" / "task-123"
        worktree.mkdir(parents=True)
        file_in_wt = worktree / "backend" / "app.py"

        assert _is_path_allowed(file_in_wt, project_root, extra_roots=(worktree,)) is True

    def test_path_outside_both_roots_denied(self, tmp_path: Path) -> None:
        """Path outside both allowed_root and extra_roots is denied."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        worktree = tmp_path / "worktrees" / "task-123"
        worktree.mkdir(parents=True)
        external = Path("/tmp/unrelated/file.py")

        assert _is_path_allowed(external, project_root, extra_roots=(worktree,)) is False

    def test_no_allowed_root_allows_all(self) -> None:
        """When allowed_root is None, all paths are allowed."""
        assert _is_path_allowed(Path("/any/path"), None) is True

    def test_empty_extra_roots_no_effect(self, tmp_path: Path) -> None:
        """Empty extra_roots tuple doesn't change behavior."""
        external = Path("/tmp/other/file.py")
        assert _is_path_allowed(external, tmp_path, extra_roots=()) is False


class TestWorktreeExecutor:
    """Tests for DirectToolExecutor with worktree-like working directories."""

    @pytest.mark.asyncio
    async def test_read_file_in_worktree(self, tmp_path: Path) -> None:
        """Executor can read files when working_dir is outside allowed_root (worktree)."""
        # Simulate: project root and separate worktree directory
        project_root = tmp_path / "project"
        project_root.mkdir()
        worktree = tmp_path / "worktrees" / "task-1"
        worktree.mkdir(parents=True)
        test_file = worktree / "code.py"
        test_file.write_text("print('hello')")

        executor = DirectToolExecutor(str(worktree))
        # Manually set allowed_root to project root (simulates KNOWN_ROOTS lookup)
        executor._allowed_root = project_root

        result = await executor.read_file("code.py")
        assert "print('hello')" in result

    @pytest.mark.asyncio
    async def test_write_file_in_worktree(self, tmp_path: Path) -> None:
        """Executor can write files in worktree working directory."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        worktree = tmp_path / "worktrees" / "task-2"
        worktree.mkdir(parents=True)

        executor = DirectToolExecutor(str(worktree))
        executor._allowed_root = project_root

        result = await executor.write_file("output.py", "x = 1")
        assert "successfully" in result.lower()
        assert (worktree / "output.py").read_text() == "x = 1"

    @pytest.mark.asyncio
    async def test_bash_in_worktree(self, tmp_path: Path) -> None:
        """Executor can run bash when working_dir is a worktree."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        worktree = tmp_path / "worktrees" / "task-3"
        worktree.mkdir(parents=True)

        executor = DirectToolExecutor(str(worktree))
        executor._allowed_root = project_root

        result = await executor.bash("pwd")
        assert str(worktree) in result
