"""Tests for direct tool executor."""

from pathlib import Path

import pytest

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

    def test_blocks_rm_rf_root(self):
        """Test that rm -rf / is blocked."""
        assert _is_blocked_command("rm -rf /") is True

    def test_allows_rm_in_directory(self):
        """Test that rm in a specific directory is allowed."""
        assert _is_blocked_command("rm -rf ./build") is False

    def test_blocks_mkfs(self):
        """Test that mkfs is blocked."""
        assert _is_blocked_command("mkfs.ext4 /dev/sda1") is True


class TestDirectToolExecutor:
    """Tests for DirectToolExecutor."""

    @pytest.fixture
    def executor(self, tmp_path: Path) -> DirectToolExecutor:
        """Create executor with temp directory."""
        return DirectToolExecutor(str(tmp_path))

    @pytest.mark.asyncio
    async def test_bash_echo(self, executor: DirectToolExecutor):
        """Test basic bash command."""
        result = await executor.bash("echo hello")
        assert "hello" in result

    @pytest.mark.asyncio
    async def test_bash_inherits_env(self, executor: DirectToolExecutor, monkeypatch):
        """Test that bash inherits environment variables."""
        monkeypatch.setenv("TEST_VAR_DIRECT", "test_value_123")
        result = await executor.bash("echo $TEST_VAR_DIRECT")
        assert "test_value_123" in result

    @pytest.mark.asyncio
    async def test_bash_blocked_command(self, executor: DirectToolExecutor):
        """Test that dangerous commands are blocked."""
        result = await executor.bash("rm -rf /")
        assert "blocked" in result.lower()

    @pytest.mark.asyncio
    async def test_bash_uses_working_dir(self, executor: DirectToolExecutor, tmp_path: Path):
        """Test that bash runs in the correct working directory."""
        result = await executor.bash("pwd")
        assert str(tmp_path) in result

    @pytest.mark.asyncio
    async def test_read_file_success(self, executor: DirectToolExecutor, tmp_path: Path):
        """Test reading a file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("line1\nline2\nline3")

        result = await executor.read_file("test.txt")
        assert "line1" in result
        assert "line2" in result

    @pytest.mark.asyncio
    async def test_read_file_absolute_path(self, executor: DirectToolExecutor, tmp_path: Path):
        """Test reading a file with absolute path."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("absolute content")

        result = await executor.read_file(str(test_file))
        assert "absolute content" in result

    @pytest.mark.asyncio
    async def test_read_file_not_found(self, executor: DirectToolExecutor):
        """Test reading non-existent file."""
        result = await executor.read_file("nonexistent.txt")
        assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_write_file_success(self, executor: DirectToolExecutor, tmp_path: Path):
        """Test writing a file."""
        result = await executor.write_file("output.txt", "test content")
        assert "successfully" in result.lower()

        written_file = tmp_path / "output.txt"
        assert written_file.exists()
        assert written_file.read_text() == "test content"

    @pytest.mark.asyncio
    async def test_write_file_creates_dirs(self, executor: DirectToolExecutor, tmp_path: Path):
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
    async def test_execute_bash(self, handler: DirectToolHandler):
        """Test bash tool via handler."""
        call = ToolCall(id="test-1", name="bash", input={"command": "echo test"})
        result = await handler.execute(call)
        assert not result.is_error
        assert "test" in result.content

    @pytest.mark.asyncio
    async def test_execute_unknown_tool(self, handler: DirectToolHandler):
        """Test unknown tool returns error."""
        call = ToolCall(id="test-1", name="unknown_tool", input={})
        result = await handler.execute(call)
        assert "unknown" in result.content.lower()


class TestStandardTools:
    """Tests for standard tool definitions."""

    def test_get_standard_tools_returns_three(self):
        """Test that standard tools include bash, read, write."""
        tools = get_standard_tools()
        names = [t.name for t in tools]
        assert "bash" in names
        assert "read_file" in names
        assert "write_file" in names

    def test_create_handler_with_workdir(self, tmp_path: Path):
        """Test handler creation with working directory."""
        handler = create_direct_handler(str(tmp_path))
        assert handler is not None
        assert handler._executor.working_dir == tmp_path
