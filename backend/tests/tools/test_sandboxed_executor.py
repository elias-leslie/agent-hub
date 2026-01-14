"""Tests for sandboxed tool executor."""

from pathlib import Path

import pytest

from app.services.tools.base import ToolCall
from app.services.tools.sandboxed_executor import (
    SandboxedToolExecutor,
    SandboxedToolHandler,
    _is_safe_path,
    create_sandboxed_handler,
    get_standard_tools,
)


class TestPathSafety:
    """Tests for path safety checks."""

    def test_safe_path_within_workdir(self, tmp_path: Path):
        """Test that paths within workdir are safe."""
        assert _is_safe_path("subdir/file.txt", tmp_path) is True

    def test_unsafe_path_escape_via_dotdot(self, tmp_path: Path):
        """Test that path traversal is blocked."""
        assert _is_safe_path("../etc/passwd", tmp_path) is False

    def test_unsafe_absolute_path(self, tmp_path: Path):
        """Test that absolute paths outside workdir are blocked."""
        assert _is_safe_path("/etc/passwd", tmp_path) is False


class TestSandboxedToolExecutor:
    """Tests for SandboxedToolExecutor."""

    @pytest.fixture
    def executor(self, tmp_path: Path) -> SandboxedToolExecutor:
        """Create executor with temp directory."""
        return SandboxedToolExecutor(str(tmp_path))

    @pytest.mark.asyncio
    async def test_bash_echo(self, executor: SandboxedToolExecutor):
        """Test basic bash command."""
        result = await executor.bash("echo hello")
        assert "hello" in result

    @pytest.mark.asyncio
    async def test_bash_blocked_command(self, executor: SandboxedToolExecutor):
        """Test that dangerous commands are blocked."""
        result = await executor.bash("rm -rf /")
        assert "blocked" in result.lower()

    @pytest.mark.asyncio
    async def test_read_file_success(self, executor: SandboxedToolExecutor, tmp_path: Path):
        """Test reading a file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("line1\nline2\nline3")

        result = await executor.read_file("test.txt")
        assert "line1" in result
        assert "line2" in result

    @pytest.mark.asyncio
    async def test_read_file_not_found(self, executor: SandboxedToolExecutor):
        """Test reading non-existent file."""
        result = await executor.read_file("nonexistent.txt")
        assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_read_file_path_escape(self, executor: SandboxedToolExecutor):
        """Test that path traversal is blocked."""
        result = await executor.read_file("../etc/passwd")
        assert "outside" in result.lower()

    @pytest.mark.asyncio
    async def test_write_file_success(self, executor: SandboxedToolExecutor, tmp_path: Path):
        """Test writing a file."""
        result = await executor.write_file("output.txt", "test content")
        assert "successfully" in result.lower()

        written_file = tmp_path / "output.txt"
        assert written_file.exists()
        assert written_file.read_text() == "test content"

    @pytest.mark.asyncio
    async def test_write_file_creates_dirs(self, executor: SandboxedToolExecutor, tmp_path: Path):
        """Test that write creates parent directories."""
        result = await executor.write_file("subdir/nested/file.txt", "nested content")
        assert "successfully" in result.lower()

        written_file = tmp_path / "subdir" / "nested" / "file.txt"
        assert written_file.exists()


class TestSandboxedToolHandler:
    """Tests for SandboxedToolHandler."""

    @pytest.fixture
    def handler(self, tmp_path: Path) -> SandboxedToolHandler:
        """Create handler with temp directory."""
        return SandboxedToolHandler(str(tmp_path))

    @pytest.mark.asyncio
    async def test_execute_bash(self, handler: SandboxedToolHandler):
        """Test bash tool via handler."""
        call = ToolCall(id="test-1", name="bash", input={"command": "echo test"})
        result = await handler.execute(call)
        assert not result.is_error
        assert "test" in result.content

    @pytest.mark.asyncio
    async def test_execute_unknown_tool(self, handler: SandboxedToolHandler):
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
        handler = create_sandboxed_handler(str(tmp_path))
        assert handler is not None
        assert handler._executor.working_dir == tmp_path
