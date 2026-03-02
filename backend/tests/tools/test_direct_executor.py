"""Tests for direct tool executor."""

from __future__ import annotations

from pathlib import Path

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
        """Test that standard tools include bash, read, write, consult_agent."""
        tools = get_standard_tools()
        names = [t.name for t in tools]
        assert "bash" in names
        assert "read_file" in names
        assert "write_file" in names
        assert "consult_agent" in names

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
