"""Tests for worktree write-boundary permission hook."""

import pytest

from app.services.tools._worktree_boundary_hook import (
    _is_write_allowed,
    create_worktree_boundary_hook,
)
from app.services.tools.base import ToolCall, ToolDecision


class TestIsWriteAllowed:
    """Unit tests for the path-checking helper."""

    def test_inside_boundary(self, tmp_path):
        boundary = tmp_path / "worktree"
        boundary.mkdir()
        target = boundary / "src" / "main.py"
        assert _is_write_allowed(target, boundary) is True

    def test_outside_boundary(self):
        from pathlib import Path

        # Use paths outside /tmp/ and ~/.claude/ to avoid the allowlist
        boundary = Path("/home/testuser/worktree")
        target = Path("/home/testuser/other-project/file.py")
        assert _is_write_allowed(target, boundary) is False

    def test_tmp_always_allowed(self, tmp_path):
        from pathlib import Path

        boundary = tmp_path / "worktree"
        boundary.mkdir()
        target = Path("/tmp/scratch/output.txt")
        assert _is_write_allowed(target, boundary) is True

    def test_claude_dir_always_allowed(self, tmp_path):
        from pathlib import Path

        boundary = tmp_path / "worktree"
        boundary.mkdir()
        target = Path.home() / ".claude" / "settings.json"
        assert _is_write_allowed(target, boundary) is True


class TestWorktreeBoundaryHook:
    """Integration tests for the full hook."""

    @pytest.mark.asyncio
    async def test_write_inside_worktree_allowed(self, tmp_path):
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        hook = create_worktree_boundary_hook(str(worktree))

        tc = ToolCall(id="1", name="write_file", input={"path": str(worktree / "file.py")})
        assert await hook(tc) == ToolDecision.ALLOW

    @pytest.mark.asyncio
    async def test_write_outside_worktree_denied(self):
        # Use paths outside /tmp/ and ~/.claude/ to avoid the write allowlist
        hook = create_worktree_boundary_hook("/home/testuser/worktree")

        tc = ToolCall(id="2", name="write_file", input={"path": "/home/testuser/other/file.py"})
        assert await hook(tc) == ToolDecision.DENY

    @pytest.mark.asyncio
    async def test_read_outside_worktree_allowed(self, tmp_path):
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        hook = create_worktree_boundary_hook(str(worktree))

        tc = ToolCall(id="3", name="read_file", input={"path": str(tmp_path / "other" / "file.py")})
        assert await hook(tc) == ToolDecision.ALLOW

    @pytest.mark.asyncio
    async def test_bash_always_allowed(self, tmp_path):
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        hook = create_worktree_boundary_hook(str(worktree))

        tc = ToolCall(id="4", name="bash", input={"command": "rm -rf /"})
        assert await hook(tc) == ToolDecision.ALLOW

    @pytest.mark.asyncio
    async def test_write_to_tmp_allowed(self, tmp_path):
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        hook = create_worktree_boundary_hook(str(worktree))

        tc = ToolCall(id="5", name="write_file", input={"path": "/tmp/scratch.txt"})
        assert await hook(tc) == ToolDecision.ALLOW

    @pytest.mark.asyncio
    async def test_write_empty_path_allowed(self, tmp_path):
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        hook = create_worktree_boundary_hook(str(worktree))

        tc = ToolCall(id="6", name="write_file", input={"path": ""})
        assert await hook(tc) == ToolDecision.ALLOW

    @pytest.mark.asyncio
    async def test_unknown_tool_allowed(self, tmp_path):
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        hook = create_worktree_boundary_hook(str(worktree))

        tc = ToolCall(id="7", name="search_files", input={"query": "foo"})
        assert await hook(tc) == ToolDecision.ALLOW
