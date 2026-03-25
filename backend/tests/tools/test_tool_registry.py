"""Tests for centralized tool registry loading and command redirect."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.tools.registry import (
    _build_redirect_patterns,
    _build_wrapper_pattern,
    _load_registry,
    get_command_redirect,
    get_registry,
)


class TestLoadRegistry:
    """Tests for registry file loading."""

    def test_loads_valid_registry(self, tmp_path: Path) -> None:
        """Test loading a valid registry JSON file."""
        registry_file = tmp_path / "tool-registry.json"
        registry_file.write_text(
            json.dumps(
                {
                    "version": 1,
                    "cmd_start": "(^|&&\\s*|;\\s*)",
                    "wrapper_allowlist": ["dt\\b"],
                    "tools": [],
                    "service_redirects": [],
                }
            )
        )
        result = _load_registry(registry_file)
        assert result is not None
        assert result["version"] == 1
        assert result["wrapper_allowlist"] == ["dt\\b"]

    def test_returns_none_for_missing_file(self, tmp_path: Path) -> None:
        """Test that missing file returns None."""
        result = _load_registry(tmp_path / "nonexistent.json")
        assert result is None

    def test_returns_none_for_invalid_json(self, tmp_path: Path) -> None:
        """Test that invalid JSON returns None."""
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not json {{{")
        result = _load_registry(bad_file)
        assert result is None


class TestBuildPatterns:
    """Tests for regex pattern building from registry data."""

    def test_build_redirect_patterns_from_tools(self) -> None:
        """Test building redirect patterns from tool entries."""
        registry = {
            "cmd_start": "(^|&&\\s*|;\\s*)",
            "tools": [
                {
                    "name": "pytest",
                    "redirect_patterns": [
                        "(\\.venv/bin/)?pytest\\b",
                        "python[0-9.]*\\s+-m\\s+pytest\\b",
                    ],
                    "redirect_message": "Use dt pytest",
                },
            ],
            "service_redirects": [
                {
                    "pattern": "systemctl\\s+restart",
                    "message": "Use restart.sh",
                },
            ],
        }
        patterns = _build_redirect_patterns(registry)
        # Should have 2 tool patterns + 1 service pattern = 3 total
        assert len(patterns) == 3
        # Each is (compiled_regex, message)
        assert patterns[0][1] == "Use dt pytest"
        assert patterns[2][1] == "Use restart.sh"

    def test_build_wrapper_pattern(self) -> None:
        """Test building wrapper allowlist regex."""
        registry = {
            "cmd_start": "(^|&&\\s*|;\\s*)",
            "wrapper_allowlist": ["dt\\b", "st\\b", "restart\\.sh\\b"],
        }
        pattern = _build_wrapper_pattern(registry)
        assert pattern is not None
        assert pattern.search("dt pytest") is not None
        assert pattern.search("st task list") is not None
        assert pattern.search("echo hello && restart.sh") is not None
        assert pattern.search("echo hello") is None


class TestGetCommandRedirect:
    """Tests for command redirect matching."""

    @pytest.fixture(autouse=True)
    def _reset_registry_cache(self) -> None:
        """Reset module-level caches between tests."""
        import app.services.tools.registry as reg_mod

        reg_mod._cached_registry = None
        reg_mod._cached_patterns = None
        reg_mod._cached_wrapper_pattern = None

    @pytest.fixture
    def registry_file(self, tmp_path: Path) -> Path:
        """Create a test registry file."""
        registry = {
            "version": 1,
            "cmd_start": "(^|&&\\s*|;\\s*)",
            "wrapper_allowlist": [
                "dt\\b",
                "dev-tools\\.sh\\b",
                "st\\b",
                "db\\b",
                "restart\\.sh\\b",
                "rebuild\\.sh\\b",
            ],
            "tools": [
                {
                    "name": "pytest",
                    "redirect_patterns": [
                        "(\\.venv/bin/)?pytest\\b",
                        "python[0-9.]*\\s+-m\\s+pytest\\b",
                    ],
                    "redirect_message": "Use 'dt pytest [args]'",
                },
                {
                    "name": "ruff",
                    "redirect_patterns": ["(\\.venv/bin/)?ruff\\b"],
                    "redirect_message": "Use 'dt ruff [args]'",
                },
                {
                    "name": "types",
                    "redirect_patterns": ["(\\.venv/bin/)?mypy\\b"],
                    "redirect_message": "Use 'dt types [args]'",
                },
                {
                    "name": "vitest",
                    "redirect_patterns": [
                        "(npx\\s+|pnpm(?:\\s+exec)?\\s+)?vitest\\b",
                    ],
                    "redirect_message": "Use 'dt vitest [args]'",
                },
            ],
            "service_redirects": [
                {
                    "pattern": "systemctl\\s+(--user\\s+)?restart\\s+(summitflow|agent-hub)",
                    "message": "Use restart.sh",
                },
                {
                    "pattern": "psql\\b",
                    "message": "Use 'db' CLI instead of raw psql.",
                },
            ],
        }
        lib_dir = tmp_path / "lib"
        lib_dir.mkdir()
        f = lib_dir / "tool-registry.json"
        f.write_text(json.dumps(registry))
        return f

    def test_blocks_raw_pytest(self, registry_file: Path) -> None:
        """Test that raw pytest is redirected."""
        with patch("app.services.tools.registry.resolve_summitflow_scripts_dir", return_value=registry_file.parent.parent):
            result = get_command_redirect("pytest tests/")
            assert result is not None
            assert "dt pytest" in result

    def test_blocks_venv_pytest(self, registry_file: Path) -> None:
        """Test that .venv/bin/pytest is redirected."""
        with patch("app.services.tools.registry.resolve_summitflow_scripts_dir", return_value=registry_file.parent.parent):
            result = get_command_redirect(".venv/bin/pytest -v")
            assert result is not None
            assert "dt pytest" in result

    def test_blocks_python_m_pytest(self, registry_file: Path) -> None:
        """Test that python -m pytest is redirected."""
        with patch("app.services.tools.registry.resolve_summitflow_scripts_dir", return_value=registry_file.parent.parent):
            result = get_command_redirect("python -m pytest tests/")
            assert result is not None

    def test_blocks_raw_ruff(self, registry_file: Path) -> None:
        """Test that raw ruff is redirected."""
        with patch("app.services.tools.registry.resolve_summitflow_scripts_dir", return_value=registry_file.parent.parent):
            result = get_command_redirect("ruff check .")
            assert result is not None
            assert "dt ruff" in result

    def test_blocks_raw_types(self, registry_file: Path) -> None:
        """Test that raw mypy is redirected."""
        with patch("app.services.tools.registry.resolve_summitflow_scripts_dir", return_value=registry_file.parent.parent):
            result = get_command_redirect("mypy app/")
            assert result is not None
            assert "dt types" in result

    def test_blocks_pnpm_vitest(self, registry_file: Path) -> None:
        """Test that pnpm vitest is redirected."""
        with patch("app.services.tools.registry.resolve_summitflow_scripts_dir", return_value=registry_file.parent.parent):
            result = get_command_redirect("pnpm vitest src/__tests__/foo.test.tsx --run")
            assert result is not None
            assert "dt vitest" in result

    def test_blocks_pnpm_exec_vitest(self, registry_file: Path) -> None:
        """Test that pnpm exec vitest is redirected."""
        with patch("app.services.tools.registry.resolve_summitflow_scripts_dir", return_value=registry_file.parent.parent):
            result = get_command_redirect("pnpm exec vitest src/__tests__/foo.test.tsx --run")
            assert result is not None
            assert "dt vitest" in result

    def test_blocks_psql(self, registry_file: Path) -> None:
        """Test that raw psql is redirected to db CLI."""
        with patch("app.services.tools.registry.resolve_summitflow_scripts_dir", return_value=registry_file.parent.parent):
            result = get_command_redirect("psql -U postgres summitflow")
            assert result is not None
            assert "db" in result

    def test_blocks_systemctl_restart(self, registry_file: Path) -> None:
        """Test that systemctl restart is redirected."""
        with patch("app.services.tools.registry.resolve_summitflow_scripts_dir", return_value=registry_file.parent.parent):
            result = get_command_redirect("systemctl --user restart summitflow")
            assert result is not None
            assert "restart.sh" in result

    def test_allows_dt_wrapper(self, registry_file: Path) -> None:
        """Test that dt commands are allowed."""
        with patch("app.services.tools.registry.resolve_summitflow_scripts_dir", return_value=registry_file.parent.parent):
            assert get_command_redirect("dt pytest tests/") is None

    def test_allows_st_wrapper(self, registry_file: Path) -> None:
        """Test that st commands are allowed."""
        with patch("app.services.tools.registry.resolve_summitflow_scripts_dir", return_value=registry_file.parent.parent):
            assert get_command_redirect("st task list") is None

    def test_allows_db_wrapper(self, registry_file: Path) -> None:
        """Test that db commands are allowed."""
        with patch("app.services.tools.registry.resolve_summitflow_scripts_dir", return_value=registry_file.parent.parent):
            assert get_command_redirect("db tables --counts") is None

    def test_allows_restart_sh(self, registry_file: Path) -> None:
        """Test that restart.sh is allowed."""
        with patch("app.services.tools.registry.resolve_summitflow_scripts_dir", return_value=registry_file.parent.parent):
            assert get_command_redirect("restart.sh") is None

    def test_allows_unrelated_command(self, registry_file: Path) -> None:
        """Test that unrelated commands pass through."""
        with patch("app.services.tools.registry.resolve_summitflow_scripts_dir", return_value=registry_file.parent.parent):
            assert get_command_redirect("echo hello") is None
            assert get_command_redirect("git status") is None
            assert get_command_redirect("ls -la") is None

    def test_blocks_chained_raw_command(self, registry_file: Path) -> None:
        """Test that raw commands after && are caught."""
        with patch("app.services.tools.registry.resolve_summitflow_scripts_dir", return_value=registry_file.parent.parent):
            result = get_command_redirect("echo done && pytest tests/")
            assert result is not None

    def test_allows_tool_name_in_string(self, registry_file: Path) -> None:
        """Test that tool names in echo strings are not blocked."""
        with patch("app.services.tools.registry.resolve_summitflow_scripts_dir", return_value=registry_file.parent.parent):
            # 'pytest' appears in an echo string, not as a command
            assert get_command_redirect("echo 'run pytest later'") is None

    def test_fallback_when_registry_missing(self, tmp_path: Path) -> None:
        """Test graceful fallback when registry file doesn't exist."""
        missing = tmp_path / "nonexistent.json"
        with patch("app.services.tools.registry.resolve_summitflow_scripts_dir", return_value=missing.parent):
            # Should not crash, just return None (allow all)
            assert get_command_redirect("pytest tests/") is None


class TestGetRegistry:
    """Tests for get_registry() public API."""

    @pytest.fixture(autouse=True)
    def _reset_registry_cache(self) -> None:
        """Reset module-level caches between tests."""
        import app.services.tools.registry as reg_mod

        reg_mod._cached_registry = None
        reg_mod._cached_patterns = None
        reg_mod._cached_wrapper_pattern = None

    def test_returns_registry_dict(self, tmp_path: Path) -> None:
        """Test get_registry returns the parsed registry."""
        registry = {
            "version": 1,
            "cmd_start": "(^|&&\\s*|;\\s*)",
            "wrapper_allowlist": [],
            "tools": [
                {
                    "name": "pytest",
                    "redirect_patterns": ["pytest\\b"],
                    "redirect_message": "Use dt",
                    "dt": {
                        "label": "TEST",
                        "binary": "pytest",
                        "args": "-q",
                        "count_method": "pytest_parse",
                        "working_dir": "backend",
                        "fallback_global": False,
                        "pass_path": False,
                    },
                }
            ],
            "service_redirects": [],
        }
        lib_dir = tmp_path / "lib"
        lib_dir.mkdir()
        f = lib_dir / "tool-registry.json"
        f.write_text(json.dumps(registry))
        with patch("app.services.tools.registry.resolve_summitflow_scripts_dir", return_value=f.parent.parent):
            result = get_registry()
            assert result is not None
            assert result["version"] == 1
            assert len(result["tools"]) == 1
            assert result["tools"][0]["dt"]["label"] == "TEST"

    def test_returns_none_when_missing(self, tmp_path: Path) -> None:
        """Test get_registry returns None when file missing."""
        with patch("app.services.tools.registry.resolve_summitflow_scripts_dir", return_value=tmp_path):
            assert get_registry() is None
