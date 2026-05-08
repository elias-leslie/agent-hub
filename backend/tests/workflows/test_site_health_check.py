"""Tests for the pure/sync helpers in site_health_check workflow."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import yaml

from app.workflows.site_health_check import (
    HealthCheckResult,
    _build_capture_blocks,
    _build_findings_prompt,
    _findings_have_issues,
    _get_frontend_url,
    _get_page_paths,
    _wake_persona_with_site_findings,
    build_user_content,
)

# ---------------------------------------------------------------------------
# _get_frontend_url
# ---------------------------------------------------------------------------


class TestGetFrontendUrl:
    pytestmark = pytest.mark.asyncio

    async def test_uses_project_index_host_before_stale_settings(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "agent-hub"
        project_dir.mkdir()
        (project_dir / ".index.yaml").write_text(
            yaml.safe_dump({"network": {"host_ip": "192.168.8.244"}})
        )
        with (
            patch.dict("os.environ", {"PROJECTS_BASE_PATH": str(tmp_path)}),
            patch("app.workflows.site_health_check._IN_DOCKER", False),
            patch("app.workflows.site_health_check.settings.host", "192.168.8.234"),
            patch("app.workflows.site_health_check.settings.st_browser_host", "192.168.8.234"),
        ):
            url = await _get_frontend_url("agent-hub")
        assert url == "http://192.168.8.244:3003"

    async def test_returns_configured_host_url_when_not_in_docker(self, tmp_path: Path) -> None:
        with (
            patch.dict("os.environ", {"PROJECTS_BASE_PATH": str(tmp_path)}),
            patch("app.workflows.site_health_check._IN_DOCKER", False),
            patch("app.workflows.site_health_check.settings.host", "192.168.8.244"),
            patch("app.workflows.site_health_check.settings.st_browser_host", "192.168.8.234"),
        ):
            url = await _get_frontend_url("summitflow")
        assert url == "http://192.168.8.244:3001"

    async def test_uses_st_browser_host_when_host_is_loopback(self, tmp_path: Path) -> None:
        with (
            patch.dict("os.environ", {"PROJECTS_BASE_PATH": str(tmp_path)}),
            patch("app.workflows.site_health_check._IN_DOCKER", False),
            patch("app.workflows.site_health_check.settings.host", "127.0.0.1"),
            patch("app.workflows.site_health_check.settings.st_browser_host", "192.168.8.245"),
        ):
            url = await _get_frontend_url("agent-hub")
        assert url == "http://192.168.8.245:3003"

    async def test_falls_back_to_st_browser_host_when_host_missing(self, tmp_path: Path) -> None:
        with (
            patch.dict("os.environ", {"PROJECTS_BASE_PATH": str(tmp_path)}),
            patch("app.workflows.site_health_check._IN_DOCKER", False),
            patch("app.workflows.site_health_check.settings.host", ""),
            patch("app.workflows.site_health_check.settings.st_browser_host", "192.168.8.245"),
        ):
            url = await _get_frontend_url("agent-hub")
        assert url == "http://192.168.8.245:3003"

    async def test_returns_service_name_url_when_in_docker(self) -> None:
        with patch("app.workflows.site_health_check._IN_DOCKER", True):
            url = await _get_frontend_url("agent-hub")
        assert url == "http://agent-hub-web:3003"

    async def test_all_known_projects_produce_urls(self, tmp_path: Path) -> None:
        from app.workflows.site_health_check import FRONTEND_SERVICES

        with (
            patch.dict("os.environ", {"PROJECTS_BASE_PATH": str(tmp_path)}),
            patch("app.workflows.site_health_check._IN_DOCKER", False),
            patch("app.workflows.site_health_check.settings.host", "192.168.8.244"),
            patch("app.workflows.site_health_check.settings.st_browser_host", "192.168.8.234"),
        ):
            for project_id in FRONTEND_SERVICES:
                url = await _get_frontend_url(project_id)
                assert url.startswith("http://192.168.8.244:")


# ---------------------------------------------------------------------------
# _get_page_paths
# ---------------------------------------------------------------------------


class TestGetPagePaths:
    def test_returns_slash_when_index_file_missing(self, tmp_path: Path) -> None:
        with patch.dict("os.environ", {"PROJECTS_BASE_PATH": str(tmp_path)}):
            paths = _get_page_paths("nonexistent-project")
        assert paths == ["/"]

    def test_reads_paths_from_index_yaml(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "my-project"
        project_dir.mkdir()
        (project_dir / ".index.yaml").write_text(
            yaml.dump({"pages": ["/home (Home)", "/about (About)", "/contact (Contact)"]})
        )
        with patch.dict("os.environ", {"PROJECTS_BASE_PATH": str(tmp_path)}):
            paths = _get_page_paths("my-project")
        assert paths == ["/home", "/about", "/contact"]

    def test_filters_dynamic_routes(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "my-project"
        project_dir.mkdir()
        (project_dir / ".index.yaml").write_text(
            yaml.dump({"pages": ["/users/:id (User)", "/home (Home)"]})
        )
        with patch.dict("os.environ", {"PROJECTS_BASE_PATH": str(tmp_path)}):
            paths = _get_page_paths("my-project")
        assert "/home" in paths
        assert not any(":" in p for p in paths)

    def test_caps_at_max_pages(self, tmp_path: Path) -> None:
        from app.workflows.site_health_check import MAX_PAGES_PER_PROJECT

        project_dir = tmp_path / "my-project"
        project_dir.mkdir()
        many_pages = [f"/page{i} (Page {i})" for i in range(20)]
        (project_dir / ".index.yaml").write_text(yaml.dump({"pages": many_pages}))
        with patch.dict("os.environ", {"PROJECTS_BASE_PATH": str(tmp_path)}):
            paths = _get_page_paths("my-project")
        assert len(paths) == MAX_PAGES_PER_PROJECT

    def test_returns_slash_on_empty_pages_list(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "my-project"
        project_dir.mkdir()
        (project_dir / ".index.yaml").write_text(yaml.dump({"pages": []}))
        with patch.dict("os.environ", {"PROJECTS_BASE_PATH": str(tmp_path)}):
            paths = _get_page_paths("my-project")
        assert paths == ["/"]

    def test_returns_slash_on_invalid_yaml(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "bad-project"
        project_dir.mkdir()
        (project_dir / ".index.yaml").write_text(":: invalid :: yaml ::")
        with patch.dict("os.environ", {"PROJECTS_BASE_PATH": str(tmp_path)}):
            paths = _get_page_paths("bad-project")
        assert paths == ["/"]

    def test_handles_paths_without_display_name(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "my-project"
        project_dir.mkdir()
        (project_dir / ".index.yaml").write_text(yaml.dump({"pages": ["/bare"]}))
        with patch.dict("os.environ", {"PROJECTS_BASE_PATH": str(tmp_path)}):
            paths = _get_page_paths("my-project")
        assert paths == ["/bare"]


# ---------------------------------------------------------------------------
# _build_capture_blocks
# ---------------------------------------------------------------------------


class TestBuildCaptureBlocks:
    def _make_capture(self, path: str = "/home", b64: str = "abc123") -> dict[str, str]:
        return {"path": path, "screenshot_b64": b64, "errors": "[]", "console": "[]"}

    def test_returns_two_blocks_image_then_text(self) -> None:
        blocks = _build_capture_blocks(self._make_capture())
        assert len(blocks) == 2
        assert blocks[0]["type"] == "image"
        assert blocks[1]["type"] == "text"

    def test_image_block_contains_base64_data(self) -> None:
        capture = self._make_capture(b64="MYSCREENSHOTDATA")
        blocks = _build_capture_blocks(capture)
        assert blocks[0]["source"]["data"] == "MYSCREENSHOTDATA"
        assert blocks[0]["source"]["type"] == "base64"
        assert blocks[0]["source"]["media_type"] == "image/png"

    def test_text_block_includes_path_and_console_data(self) -> None:
        capture = self._make_capture(path="/dashboard")
        capture["errors"] = "TypeError: x"
        capture["console"] = "console log here"
        blocks = _build_capture_blocks(capture)
        text = blocks[1]["text"]
        assert "Page: /dashboard" in text
        assert "TypeError: x" in text
        assert "console log here" in text

    def test_console_data_truncated_at_800_chars(self) -> None:
        long_error = "e" * 2000
        capture = self._make_capture()
        capture["errors"] = long_error
        blocks = _build_capture_blocks(capture)
        # The text block contains the error truncated to 800
        assert long_error[:800] in blocks[1]["text"]
        assert long_error[801:] not in blocks[1]["text"]


# ---------------------------------------------------------------------------
# build_user_content
# ---------------------------------------------------------------------------


class TestBuildUserContent:
    def _make_capture(self, path: str) -> dict[str, str]:
        return {"path": path, "screenshot_b64": "b64data", "errors": "none", "console": "none"}

    def test_returns_two_blocks_per_capture_plus_analysis_instruction(self) -> None:
        captures = [self._make_capture("/home"), self._make_capture("/about")]
        content = build_user_content(captures, "my-project", "http://localhost:3001")
        # 2 captures x 2 blocks each + 1 instruction = 5 total
        assert len(content) == 5

    def test_last_block_contains_project_and_url(self) -> None:
        captures = [self._make_capture("/")]
        content = build_user_content(captures, "summitflow", "http://localhost:3001")
        last = content[-1]
        assert last["type"] == "text"
        assert "summitflow" in last["text"]
        assert "http://localhost:3001" in last["text"]

    def test_last_block_references_capture_count(self) -> None:
        captures = [self._make_capture(f"/page{i}") for i in range(3)]
        content = build_user_content(captures, "proj", "http://x")
        assert "3 page(s)" in content[-1]["text"]


# ---------------------------------------------------------------------------
# _findings_have_issues
# ---------------------------------------------------------------------------


class TestFindingsHaveIssues:
    @pytest.mark.parametrize(
        "content",
        [
            "Critical: The homepage fails to render",
            "WARNING: Slow response on /about",
            "error: TypeError in console",
            "Broken: CSS not loading",
            "Failed to load: /api/health returned 500",
        ],
    )
    def test_detects_issue_keywords(self, content: str) -> None:
        assert _findings_have_issues(content) is True

    def test_returns_false_for_healthy_output(self) -> None:
        assert _findings_have_issues("No issues found.") is False
        assert _findings_have_issues("All pages loaded successfully.") is False
        assert _findings_have_issues("Everything looks healthy.") is False

    def test_keyword_must_be_at_line_start(self) -> None:
        # "critical" buried mid-sentence should not match
        assert _findings_have_issues("The UI looks good; no critical issues.") is False

    def test_matches_across_multiple_lines(self) -> None:
        text = "Page /home looks fine.\nCritical: login broken."
        assert _findings_have_issues(text) is True


# ---------------------------------------------------------------------------
# _build_findings_prompt
# ---------------------------------------------------------------------------


class TestBuildFindingsPrompt:
    def _make_result(self, findings: dict[str, str]) -> HealthCheckResult:
        issues = sum(1 for f in findings.values() if f and not f.startswith("Error"))
        return HealthCheckResult(
            status="issues_found",
            projects_checked=len(findings),
            projects_with_issues=issues,
            project_findings=findings,
        )

    def test_returns_none_when_all_findings_are_errors(self) -> None:
        result = self._make_result({"summitflow": "Error analyzing summitflow: timeout"})
        assert _build_findings_prompt(result) is None

    def test_returns_none_when_no_findings(self) -> None:
        result = self._make_result({})
        assert _build_findings_prompt(result) is None

    def test_includes_project_name_in_prompt(self) -> None:
        result = self._make_result({"agent-hub": "Warning: slow response on /dashboard"})
        prompt = _build_findings_prompt(result)
        assert prompt is not None
        assert "## agent-hub" in prompt

    def test_prompt_includes_checked_and_issue_counts(self) -> None:
        result = self._make_result(
            {"summitflow": "Critical: crash", "a-term": "No issues found."}
        )
        prompt = _build_findings_prompt(result)
        assert prompt is not None
        assert str(result.projects_checked) in prompt
        assert str(result.projects_with_issues) in prompt

    def test_finding_text_truncated_at_2000_chars(self) -> None:
        long_finding = "warning: " + "x" * 3000
        result = self._make_result({"proj": long_finding})
        prompt = _build_findings_prompt(result)
        assert prompt is not None
        assert "x" * 1201 not in prompt

    def test_skips_error_prefixed_findings(self) -> None:
        result = self._make_result(
            {"bad-project": "Error: could not connect", "good-project": "Critical: crash"}
        )
        prompt = _build_findings_prompt(result)
        assert prompt is not None
        assert "bad-project" not in prompt
        assert "good-project" in prompt

    def test_keeps_only_actionable_lines_in_prompt(self) -> None:
        result = self._make_result(
            {
                "agent-hub": "\n".join(
                    [
                        "Info: layout structure is intact.",
                        "Warning: login CTA is off-screen on /agents",
                        "Critical: /chat fails to render",
                    ]
                )
            }
        )

        prompt = _build_findings_prompt(result, project_id="agent-hub")

        assert prompt is not None
        assert "Info:" not in prompt
        assert "Warning: login CTA is off-screen on /agents" in prompt
        assert "Critical: /chat fails to render" in prompt


@pytest.mark.asyncio
async def test_wake_persona_dispatches_one_project_scoped_wake_per_actionable_project() -> None:
    db = AsyncMock()

    @asynccontextmanager
    async def _session():
        yield db

    resolved_persona = SimpleNamespace(
        model="codex/gpt-5.4",
        provider="codex",
        agent=SimpleNamespace(
            primary_model_id="codex/gpt-5.4",
            temperature=0.2,
            thinking_level="medium",
        ),
    )
    result = HealthCheckResult(
        status="issues_found",
        projects_checked=3,
        projects_with_issues=2,
        project_findings={
            "agent-hub": "Warning: login CTA is off-screen on /agents",
            "summitflow": "Error analyzing summitflow: timeout",
            "portfolio-ai": "Critical: dashboard crashes on load",
        },
    )

    with (
        patch("app.db.async_session", _session),
        patch(
            "app.services.agent_routing_utils.resolve_agent",
            new_callable=AsyncMock,
            return_value=resolved_persona,
        ),
        patch("app.workflows.persona_wake.agent_wake_task.run_no_wait") as mock_run_no_wait,
    ):
        await _wake_persona_with_site_findings(result)

    assert mock_run_no_wait.call_count == 2
    wake_inputs = [call.args[0] for call in mock_run_no_wait.call_args_list]
    assert {wake.project_id for wake in wake_inputs} == {"agent-hub", "portfolio-ai"}
    assert all(wake.event_type == "site_health_check" for wake in wake_inputs)
