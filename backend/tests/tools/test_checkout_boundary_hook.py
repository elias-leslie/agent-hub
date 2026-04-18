"""Tests for checkout write-boundary permission hook."""

import pytest

from app.services.tools._checkout_boundary_hook import (
    _is_write_allowed,
    _resolve_target_path,
    create_checkout_boundary_hook,
)
from app.services.tools.base import ToolCall, ToolDecision


class TestIsWriteAllowed:
    """Unit tests for the path-checking helper."""

    def test_inside_boundary(self, tmp_path):
        boundary = tmp_path / "checkout"
        boundary.mkdir()
        target = boundary / "src" / "main.py"
        assert _is_write_allowed(target, boundary) is True

    def test_outside_boundary(self):
        from pathlib import Path

        # Use paths outside /tmp/ and ~/.claude/ to avoid the allowlist
        boundary = Path("/home/testuser/checkout")
        target = Path("/home/testuser/other-project/file.py")
        assert _is_write_allowed(target, boundary) is False

    def test_tmp_always_allowed(self, tmp_path):
        from pathlib import Path

        boundary = tmp_path / "checkout"
        boundary.mkdir()
        target = Path("/tmp/scratch/output.txt")
        assert _is_write_allowed(target, boundary) is True

    def test_claude_dir_always_allowed(self, tmp_path):
        from pathlib import Path

        boundary = tmp_path / "checkout"
        boundary.mkdir()
        target = Path.home() / ".claude" / "settings.json"
        assert _is_write_allowed(target, boundary) is True

    def test_resolve_target_path_uses_boundary_for_relative_paths(self, tmp_path):
        boundary = tmp_path / "checkout"
        boundary.mkdir()

        resolved = _resolve_target_path("backend/app/main.py", boundary)

        assert resolved == (boundary / "backend/app/main.py").resolve()


class TestCheckoutBoundaryHook:
    """Integration tests for the full hook."""

    @pytest.mark.asyncio
    async def test_write_inside_checkout_allowed(self, tmp_path):
        checkout = tmp_path / "checkout"
        checkout.mkdir()
        hook = create_checkout_boundary_hook(str(checkout))

        tc = ToolCall(id="1", name="write_file", input={"path": str(checkout / "file.py")})
        assert await hook(tc) == ToolDecision.ALLOW

    @pytest.mark.asyncio
    async def test_relative_write_inside_checkout_allowed(self, tmp_path):
        checkout = tmp_path / "checkout"
        checkout.mkdir()
        hook = create_checkout_boundary_hook(str(checkout))

        tc = ToolCall(id="1a", name="write_file", input={"path": "backend/cli/file.py"})
        assert await hook(tc) == ToolDecision.ALLOW

    @pytest.mark.asyncio
    async def test_write_outside_checkout_denied(self):
        # Use paths outside /tmp/ and ~/.claude/ to avoid the write allowlist
        hook = create_checkout_boundary_hook("/home/testuser/checkout")

        tc = ToolCall(id="2", name="write_file", input={"path": "/home/testuser/other/file.py"})
        assert await hook(tc) == ToolDecision.DENY

    @pytest.mark.asyncio
    async def test_read_outside_checkout_allowed(self, tmp_path):
        checkout = tmp_path / "checkout"
        checkout.mkdir()
        hook = create_checkout_boundary_hook(str(checkout))

        tc = ToolCall(id="3", name="read_file", input={"path": str(tmp_path / "other" / "file.py")})
        assert await hook(tc) == ToolDecision.ALLOW

    @pytest.mark.asyncio
    async def test_bash_always_allowed(self, tmp_path):
        checkout = tmp_path / "checkout"
        checkout.mkdir()
        hook = create_checkout_boundary_hook(str(checkout))

        tc = ToolCall(id="4", name="bash", input={"command": "rm -rf /"})
        assert await hook(tc) == ToolDecision.ALLOW

    @pytest.mark.asyncio
    async def test_write_to_tmp_allowed(self, tmp_path):
        checkout = tmp_path / "checkout"
        checkout.mkdir()
        hook = create_checkout_boundary_hook(str(checkout))

        tc = ToolCall(id="5", name="write_file", input={"path": "/tmp/scratch.txt"})
        assert await hook(tc) == ToolDecision.ALLOW

    @pytest.mark.asyncio
    async def test_write_empty_path_allowed(self, tmp_path):
        checkout = tmp_path / "checkout"
        checkout.mkdir()
        hook = create_checkout_boundary_hook(str(checkout))

        tc = ToolCall(id="6", name="write_file", input={"path": ""})
        assert await hook(tc) == ToolDecision.ALLOW

    @pytest.mark.asyncio
    async def test_unknown_tool_allowed(self, tmp_path):
        checkout = tmp_path / "checkout"
        checkout.mkdir()
        hook = create_checkout_boundary_hook(str(checkout))

        tc = ToolCall(id="7", name="search_files", input={"query": "foo"})
        assert await hook(tc) == ToolDecision.ALLOW

    @pytest.mark.asyncio
    async def test_write_file_path_key_inside_allowed(self, tmp_path):
        """Claude SDK sends file_path instead of path — must be checked."""
        checkout = tmp_path / "checkout"
        checkout.mkdir()
        hook = create_checkout_boundary_hook(str(checkout))

        tc = ToolCall(id="8", name="write_file", input={"file_path": str(checkout / "src" / "main.py")})
        assert await hook(tc) == ToolDecision.ALLOW

    @pytest.mark.asyncio
    async def test_write_file_path_key_outside_denied(self):
        """Claude SDK sends file_path — writes outside boundary must be denied."""
        hook = create_checkout_boundary_hook("/home/testuser/checkout")

        tc = ToolCall(id="9", name="write_file", input={"file_path": "/home/testuser/other/escape.py"})
        assert await hook(tc) == ToolDecision.DENY

    @pytest.mark.asyncio
    async def test_file_path_key_preferred_over_empty_path(self, tmp_path):
        """When path is empty but file_path is set, file_path should be used."""
        checkout = tmp_path / "checkout"
        checkout.mkdir()
        hook = create_checkout_boundary_hook(str(checkout))

        tc = ToolCall(
            id="10", name="write_file",
            input={"path": "", "file_path": str(checkout / "file.py")},
        )
        assert await hook(tc) == ToolDecision.ALLOW

    @pytest.mark.asyncio
    async def test_edit_normalized_to_write_file_denied(self):
        """Edit tool is normalized to write_file by SDK map — boundary must apply."""
        # Edit → write_file normalization happens in DirectToolHandler.execute()
        # so the hook sees write_file with file_path key
        hook = create_checkout_boundary_hook("/home/testuser/checkout")

        tc = ToolCall(
            id="11", name="write_file",
            input={"file_path": "/home/testuser/other/escape.py", "old_string": "x", "new_string": "y"},
        )
        assert await hook(tc) == ToolDecision.DENY
