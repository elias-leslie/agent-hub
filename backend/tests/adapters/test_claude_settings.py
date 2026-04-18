"""Tests for Claude SDK settings-based write boundary enforcement.

Verifies that the settings builder and PreToolUse hook correctly enforce
checkout write boundaries inside the Claude subprocess.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


class TestBuildBoundarySettings:
    """Tests for build_boundary_settings()."""

    def test_returns_permissions_with_allow_patterns(self) -> None:
        settings = self._build("/tmp/checkout")
        assert "permissions" in settings
        assert "allow" in settings["permissions"]
        assert isinstance(settings["permissions"]["allow"], list)

    def test_default_mode_is_accept_edits(self) -> None:
        settings = self._build("/tmp/checkout")
        assert settings["permissions"]["defaultMode"] == "acceptEdits"

    def test_contains_resolved_write_patterns(self) -> None:
        settings = self._build("/tmp/checkout")
        allow = settings["permissions"]["allow"]
        assert "Write(/tmp/checkout/**)" in allow
        assert "Edit(/tmp/checkout/**)" in allow

    def test_contains_relative_write_patterns(self) -> None:
        settings = self._build("/tmp/checkout")
        allow = settings["permissions"]["allow"]
        assert "Write(./**)" in allow
        assert "Edit(./**)" in allow

    def test_contains_tmp_allowlist(self) -> None:
        settings = self._build("/tmp/checkout")
        allow = settings["permissions"]["allow"]
        assert "Write(/tmp/**)" in allow
        assert "Edit(/tmp/**)" in allow

    def test_contains_claude_home_allowlist(self) -> None:
        settings = self._build("/tmp/checkout")
        allow = settings["permissions"]["allow"]
        home_claude = str(Path.home() / ".claude")
        assert f"Write({home_claude}/**)" in allow
        assert f"Edit({home_claude}/**)" in allow

    def test_read_tool_unrestricted(self) -> None:
        settings = self._build("/tmp/checkout")
        allow = settings["permissions"]["allow"]
        assert "Read(*)" in allow
        assert "Glob(*)" not in allow
        assert "Grep(*)" not in allow

    def test_bash_unrestricted(self) -> None:
        settings = self._build("/tmp/checkout")
        allow = settings["permissions"]["allow"]
        assert "Bash(*)" in allow

    def test_mcp_tools_unrestricted(self) -> None:
        settings = self._build("/tmp/checkout")
        allow = settings["permissions"]["allow"]
        assert "mcp__*(*)" in allow

    def test_claude_native_web_tools_not_allowed(self) -> None:
        settings = self._build("/tmp/checkout")
        allow = settings["permissions"]["allow"]
        assert "WebFetch(*)" not in allow
        assert "WebSearch(*)" not in allow

    def test_resolves_symlinks(self) -> None:
        """Path should be resolved (no symlinks in allow patterns)."""
        settings = self._build("/tmp/checkout")
        allow = settings["permissions"]["allow"]
        # /tmp may resolve to /private/tmp on macOS; regardless, it should be resolved
        resolved = str(Path("/tmp/checkout").resolve())
        assert f"Write({resolved}/**)" in allow

    @staticmethod
    def _build(working_dir: str) -> dict[str, Any]:
        from app.adapters._claude_settings import build_boundary_settings

        return build_boundary_settings(working_dir)


class TestWriteBoundarySettings:
    """Tests for write_boundary_settings() temp file output."""

    def test_writes_valid_json_file(self) -> None:
        from app.adapters._claude_settings import write_boundary_settings

        path = write_boundary_settings("/tmp/checkout")
        assert Path(path).exists()

        with open(path) as f:
            data = json.load(f)
        assert "permissions" in data
        assert data["permissions"]["defaultMode"] == "acceptEdits"

        # Clean up
        Path(path).unlink(missing_ok=True)

    def test_returns_string_path(self) -> None:
        from app.adapters._claude_settings import write_boundary_settings

        path = write_boundary_settings("/tmp/checkout")
        assert isinstance(path, str)
        assert path.endswith(".json")

        Path(path).unlink(missing_ok=True)


class TestBuildBoundaryHook:
    """Tests for the PreToolUse hook that enforces write boundaries."""

    @pytest.mark.asyncio
    async def test_allows_write_inside_boundary(self) -> None:
        hook = self._get_hook("/tmp/checkout")
        result = await self._call_hook(hook, "Write", {"file_path": "/tmp/checkout/foo.py"})
        assert self._is_allowed(result)

    @pytest.mark.asyncio
    async def test_blocks_write_outside_boundary(self) -> None:
        hook = self._get_hook("/tmp/checkout")
        result = await self._call_hook(hook, "Write", {"file_path": "/home/user/evil.py"})
        assert self._is_denied(result)

    @pytest.mark.asyncio
    async def test_blocks_edit_outside_boundary(self) -> None:
        hook = self._get_hook("/tmp/checkout")
        result = await self._call_hook(hook, "Edit", {"file_path": "/home/user/evil.py"})
        assert self._is_denied(result)

    @pytest.mark.asyncio
    async def test_allows_write_to_tmp(self) -> None:
        hook = self._get_hook("/home/user/checkout")
        result = await self._call_hook(hook, "Write", {"file_path": "/tmp/scratch.txt"})
        assert self._is_allowed(result)

    @pytest.mark.asyncio
    async def test_allows_write_to_claude_home(self) -> None:
        hook = self._get_hook("/tmp/checkout")
        claude_path = str(Path.home() / ".claude" / "test.json")
        result = await self._call_hook(hook, "Write", {"file_path": claude_path})
        assert self._is_allowed(result)

    @pytest.mark.asyncio
    async def test_allows_read_tool(self) -> None:
        hook = self._get_hook("/tmp/checkout")
        result = await self._call_hook(hook, "Read", {"file_path": "/etc/passwd"})
        assert self._is_allowed(result)

    @pytest.mark.asyncio
    async def test_allows_bash_tool(self) -> None:
        hook = self._get_hook("/tmp/checkout")
        result = await self._call_hook(hook, "Bash", {"command": "rm -rf /"})
        assert self._is_allowed(result)

    @pytest.mark.asyncio
    async def test_blocks_persona_raw_git_commit_bash(self) -> None:
        hook = self._get_hook("/tmp/checkout", agent_slug="persona")
        result = await self._call_hook(hook, "Bash", {"command": "git commit -m 'test'"})
        assert self._is_denied(result)

    @pytest.mark.asyncio
    async def test_allows_non_persona_raw_git_commit_bash(self) -> None:
        hook = self._get_hook("/tmp/checkout", agent_slug="coder")
        result = await self._call_hook(hook, "Bash", {"command": "git commit -m 'test'"})
        assert self._is_allowed(result)

    @pytest.mark.asyncio
    async def test_blocks_multiedit_outside_boundary(self) -> None:
        hook = self._get_hook("/tmp/checkout")
        result = await self._call_hook(hook, "MultiEdit", {"file_path": "/home/user/evil.py"})
        assert self._is_denied(result)

    @pytest.mark.asyncio
    async def test_allows_write_with_no_path(self) -> None:
        """Write with empty path should be allowed (let Claude handle the error)."""
        hook = self._get_hook("/tmp/checkout")
        result = await self._call_hook(hook, "Write", {})
        assert self._is_allowed(result)

    @pytest.mark.asyncio
    async def test_deny_message_contains_path_info(self) -> None:
        hook = self._get_hook("/tmp/checkout")
        result = await self._call_hook(hook, "Write", {"file_path": "/evil/path.py"})
        output = result.get("hookSpecificOutput", {})
        reason = output.get("permissionDecisionReason", "")
        assert "/evil/path.py" in reason
        assert "/tmp/checkout" in reason

    @pytest.mark.asyncio
    async def test_blocks_write_with_sensitive_content(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _fake_scan(path: str, content: str, **_: Any) -> str | None:
            if "SIMULATED_SECRET_TOKEN" in content:
                return "Secret-like credential detected by gitleaks"
            return None

        monkeypatch.setattr(
            "app.adapters._claude_settings.scan_runtime_sensitive_content",
            _fake_scan,
        )

        hook = self._get_hook("/tmp/checkout")
        result = await self._call_hook(
            hook,
            "Write",
            {
                "file_path": "/tmp/checkout/.env",
                "content": "TOKEN=SIMULATED_SECRET_TOKEN_123",
            },
        )
        assert self._is_denied(result)

    @staticmethod
    def _get_hook(working_dir: str, agent_slug: str | None = None) -> Any:
        from app.adapters._claude_settings import build_boundary_hook

        hooks = build_boundary_hook(working_dir, agent_slug=agent_slug)
        return hooks["PreToolUse"][0].hooks[0]

    @staticmethod
    async def _call_hook(hook: Any, tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
        input_data = {
            "hook_event_name": "PreToolUse",
            "session_id": "test",
            "tool_name": tool_name,
            "tool_input": tool_input,
            "tool_use_id": "test-id",
        }
        return await hook(input_data, "test-id", {"signal": None})

    @staticmethod
    def _is_allowed(result: dict[str, Any]) -> bool:
        """Check if hook result means 'allowed' (empty dict or no deny)."""
        if not result:
            return True
        output = result.get("hookSpecificOutput", {})
        return output.get("permissionDecision") != "deny"

    @staticmethod
    def _is_denied(result: dict[str, Any]) -> bool:
        """Check if hook result means 'denied'."""
        output = result.get("hookSpecificOutput", {})
        return output.get("permissionDecision") == "deny"
