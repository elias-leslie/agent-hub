"""Site health check workflow — proactive frontend monitoring via vision analysis."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml
from hatchet_sdk import ConcurrencyExpression, ConcurrencyLimitStrategy, Context
from pydantic import BaseModel

from app.config import settings
from app.hatchet_app import hatchet
from app.utils.safe_subprocess import create_process

logger = logging.getLogger(__name__)

_BROWSER_CDP_PORT = 9222
_WORKSPACE_BASE = Path("/srv/workspaces/projects")
_LOOPBACK_HOSTS = {"", "127.0.0.1", "localhost"}

_IN_DOCKER = os.path.exists("/.dockerenv") or os.environ.get("DOCKER_CONTAINER")

# Project → (Docker service name, port) mapping.
FRONTEND_SERVICES: dict[str, tuple[str, int]] = {
    "summitflow": ("summitflow-web", 3001),
    "agent-hub": ("agent-hub-web", 3003),
    "portfolio-ai": ("portfolio-web", 3000),
    "a-term": ("a-term-web", 3002),
    "monkey-fight": ("monkey-fight", 4001),
}

# Legacy alias used by callers that only need the port
FRONTEND_PORTS: dict[str, int] = {k: v[1] for k, v in FRONTEND_SERVICES.items()}

MAX_PAGES_PER_PROJECT = 5
CHECK_TIMEOUT_PER_PROJECT = 180  # seconds
MAX_TRIAGE_LINES_PER_PROJECT = 6
MAX_TRIAGE_CHARS_PER_PROJECT = 1200
_ACTIONABLE_FINDING_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(critical|warning|error|broken|failed to load)\b",
    re.IGNORECASE,
)


async def _read_project_index(project_id: str) -> dict[str, Any] | None:
    """Read a project's canonical index metadata."""
    index_path = _projects_base_path() / project_id / ".index.yaml"

    def _read() -> dict[str, Any] | None:
        if not index_path.is_file():
            return None
        data = yaml.safe_load(index_path.read_text())
        return data if isinstance(data, dict) else None

    try:
        return await asyncio.to_thread(_read)
    except Exception:
        logger.debug("Failed to read project index for %s", project_id, exc_info=True)
        return None


def _projects_base_path() -> Path:
    return Path(os.environ.get("PROJECTS_BASE_PATH", str(_WORKSPACE_BASE)))


def _index_frontend_host(data: dict[str, Any] | None) -> str:
    if not data:
        return ""

    network = data.get("network")
    if isinstance(network, dict):
        host_ip = network.get("host_ip")
        if isinstance(host_ip, str) and host_ip.strip():
            return host_ip.strip()

    urls = data.get("urls")
    if isinstance(urls, dict):
        frontend_url = urls.get("frontend")
        if isinstance(frontend_url, str) and frontend_url.strip():
            hostname = urlparse(frontend_url).hostname or ""
            if hostname and hostname not in _LOOPBACK_HOSTS:
                return hostname
    return ""


def _settings_frontend_host() -> str:
    configured_host = settings.host.strip()
    browser_host = settings.st_browser_host.strip()
    return browser_host if configured_host in _LOOPBACK_HOSTS else configured_host


async def _get_frontend_url(project_id: str) -> str:
    """Return base URL for a project's frontend."""
    service_name, port = FRONTEND_SERVICES[project_id]
    if _IN_DOCKER:
        return f"http://{service_name}:{port}"
    index_host = _index_frontend_host(await _read_project_index(project_id))
    host = index_host or _settings_frontend_host()
    return f"http://{host}:{port}"


class HealthCheckResult(BaseModel):
    status: str
    projects_checked: int = 0
    projects_with_issues: int = 0
    project_findings: dict[str, str] = {}
    error: str | None = None


async def _run_cmd(*args: str, timeout: int = 30) -> str:
    """Run a subprocess command and return stdout. Raises on non-zero exit."""
    proc = await create_process(
        *args,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(
            f"Command {args} failed (exit {proc.returncode}): {stderr.decode().strip()}"
        )
    return stdout.decode().strip()


def _agent_browser_cdp_args() -> list[str]:
    """Return --cdp args for agent-browser so it attaches to the shared Chrome on the test VM.

    Reads settings in priority order: explicit web_fetch_browser_cdp_url → st_browser_host.
    Falls back to an empty list when neither is configured (e.g. in CI).
    """
    cdp_url = settings.web_fetch_browser_cdp_url.strip()
    if cdp_url:
        return ["--cdp", cdp_url]
    host = settings.st_browser_host.strip()
    if host:
        return ["--cdp", f"http://{host}:{_BROWSER_CDP_PORT}"]
    return []


async def _run_browser_cmd(*args: str, timeout: int = 30) -> str:
    """Run agent-browser with CDP connection args prepended.

    Without --cdp the CLI falls back to launching a bundled Chromium, which fails in
    the native runtime because the required shared libraries (libnspr4.so, etc.) are
    not present on the host.  Passing --cdp attaches to the existing Chrome on VM 100.
    """
    return await _run_cmd("agent-browser", *_agent_browser_cdp_args(), *args, timeout=timeout)


def _get_page_paths(project_id: str) -> list[str]:
    """Read page paths from project's .index.yaml, filtering dynamic routes. Falls back to ["/"]."""
    index_path = _projects_base_path() / project_id / ".index.yaml"
    if not index_path.exists():
        logger.warning("Index file not found for %s at %s; defaulting to '/'", project_id, index_path)
        return ["/"]

    try:
        data = yaml.safe_load(index_path.read_text())
    except Exception:
        logger.warning("Failed to parse %s, defaulting to '/'", index_path, exc_info=True)
        return ["/"]

    paths = [
        entry.split(" (")[0].strip()
        for entry in data.get("pages", [])
        if ":" not in entry.split(" (")[0].strip()
    ]
    return paths[:MAX_PAGES_PER_PROJECT] if paths else ["/"]


async def _navigate_to_page(url: str, page_path: str) -> None:
    """Clear previous page state and navigate to a new page."""
    page_url = url.rstrip("/") + page_path
    with contextlib.suppress(Exception):
        await _run_browser_cmd("errors", "--clear")
    with contextlib.suppress(Exception):
        await _run_browser_cmd("console", "--clear")
    await _run_browser_cmd("open", page_url)
    await _run_browser_cmd("wait", "--load", "networkidle", timeout=30)


async def _take_screenshot() -> str:
    """Take a browser screenshot and return its base64-encoded content."""
    with contextlib.suppress(Exception):
        raw = await _run_browser_cmd("screenshot", "--json")
        data = json.loads(raw)
        path = (data.get("data") or {}).get("path", "") if isinstance(data, dict) else ""
        if path:
            return base64.b64encode(Path(path).read_bytes()).decode()
    return ""


async def _collect_console_data() -> tuple[str, str]:
    """Collect console errors and output from the browser."""
    errors = console = ""
    with contextlib.suppress(Exception):
        errors = await _run_browser_cmd("errors", "--json")
    with contextlib.suppress(Exception):
        console = await _run_browser_cmd("console", "--json")
    return errors or "No errors captured", console or "No console output captured"


async def _capture_page(url: str, page_path: str, is_first: bool) -> dict[str, str]:
    """Navigate to a page, screenshot, and collect console data. Returns path/screenshot_b64/errors/console dict."""
    if not is_first:
        await _navigate_to_page(url, page_path)
    screenshot_b64 = await _take_screenshot()
    errors, console = await _collect_console_data()
    return {"path": page_path, "screenshot_b64": screenshot_b64, "errors": errors, "console": console}


async def _capture_page_safe(
    project_id: str, url: str, page_path: str, is_first: bool
) -> dict[str, str] | None:
    """Call _capture_page and return None on any failure."""
    try:
        return await _capture_page(url, page_path, is_first=is_first)
    except Exception as e:
        logger.warning("Failed to capture %s%s: %s", project_id, page_path, e)
        return None


async def run_browser_captures(
    project_id: str, url: str, page_paths: list[str]
) -> list[dict[str, str]]:
    """Open a browser session and capture screenshots for each page path."""
    try:
        await _run_browser_cmd("open", url + page_paths[0])
        await _run_browser_cmd("wait", "--load", "networkidle", timeout=60)
    except Exception as e:
        with contextlib.suppress(Exception):
            await _run_browser_cmd("close")
        raise RuntimeError(f"Failed to load {url}: {e}") from e

    captures: list[dict[str, str]] = []
    try:
        for i, page_path in enumerate(page_paths):
            capture = await _capture_page_safe(project_id, url, page_path, is_first=(i == 0))
            if capture and capture["screenshot_b64"]:
                captures.append(capture)
    finally:
        with contextlib.suppress(Exception):
            await _run_browser_cmd("close")

    return captures


def _build_capture_blocks(capture: dict[str, str]) -> list[dict[str, Any]]:
    """Return [image_block, text_block] for a single page capture."""
    return [
        {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": capture["screenshot_b64"]},
        },
        {
            "type": "text",
            "text": (
                f"Page: {capture['path']}\n"
                f"Console errors: {capture['errors'][:800]}\n"
                f"Console output: {capture['console'][:800]}"
            ),
        },
    ]


def build_user_content(
    captures: list[dict[str, str]], project_id: str, url: str
) -> list[dict[str, Any]]:
    """Build the vision-model content block list from a set of page captures."""
    content: list[dict[str, Any]] = []
    for capture in captures:
        content.extend(_build_capture_blocks(capture))
    content.append(
        {
            "type": "text",
            "text": (
                f"\nAnalyze these {len(captures)} page(s) of the {project_id} "
                f"frontend at {url}. Report each finding with severity "
                "(critical/warning/info) and which page it affects. "
                "If everything looks healthy, say 'No issues found.'"
            ),
        }
    )
    return content


def _findings_have_issues(content: str) -> bool:
    """Return True if the analysis content indicates site issues."""
    return bool(
        re.search(
            r"^(critical|warning|error|broken|failed to load)\b",
            content,
            re.IGNORECASE | re.MULTILINE,
        )
    )


def _extract_actionable_findings(findings: str) -> list[str]:
    """Return unique actionable finding lines, trimmed for persona triage."""
    actionable: list[str] = []
    seen: set[str] = set()
    for raw_line in findings.splitlines():
        line = raw_line.strip()
        if not line or not _ACTIONABLE_FINDING_RE.match(line):
            continue
        normalized = line.lstrip("-* ").strip()
        dedupe_key = normalized.casefold()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        actionable.append(normalized)
        if len(actionable) >= MAX_TRIAGE_LINES_PER_PROJECT:
            break
    return actionable


def _build_project_triage_section(project_id: str, findings: str) -> str | None:
    """Return a compact per-project issue block for persona triage."""
    if not findings or findings.startswith("Error"):
        return None
    actionable = _extract_actionable_findings(findings)
    if not actionable:
        return None
    body = "\n".join(f"- {line}" for line in actionable)
    return f"## {project_id}\n{body[:MAX_TRIAGE_CHARS_PER_PROJECT]}"


async def _try_model_analysis(
    model: str,
    messages: list[dict[str, Any]],
    temperature: float,
    project_id: str,
    db: Any,
) -> tuple[str, bool] | tuple[None, str]:
    """Attempt analysis with a single model. Returns (content, has_issues) or (None, reason)."""
    from app.api.complete.core import complete_internal
    from app.routing.registry import get_provider_for_model

    try:
        provider = get_provider_for_model(model)
        result = await complete_internal(
            messages=messages,
            model=model,
            provider=provider,
            temperature=temperature,
            project_id=project_id,
            db=db,
            agent_slug="site-checker",
            request_source="site_health_check",
            use_memory=False,
            max_turns=1,
            execute_tools=False,
        )
        content = result.content or ""
        return content[:4000], _findings_have_issues(content)
    except Exception as e:
        logger.warning("Model %s failed for %s: %s", model, project_id, e)
        return None, str(e)


async def analyze_captures(
    project_id: str,
    user_content: list[dict[str, Any]],
) -> tuple[str, bool]:
    """Send screenshots to a vision model; tries primary then fallbacks. Returns (findings, has_issues)."""
    from app.db import async_session
    from app.services.agent_routing_utils import resolve_agent

    try:
        async with async_session() as db:
            resolved = await resolve_agent("site-checker", db)
            models = [resolved.model, *(resolved.agent.fallback_models or [])]
            system_prompt = resolved.agent.system_prompt or "Analyze the screenshot and report issues."
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ]
            failures: list[str] = []
            for model in models:
                result = await _try_model_analysis(model, messages, resolved.agent.temperature, project_id, db)
                if result[0] is not None:
                    return result
                failures.append(f"{model}: {result[1]}")
            return f"All models failed for {project_id}. Details: {'; '.join(failures)}", True
    except Exception as e:
        logger.warning("Site check analysis failed for %s: %s", project_id, e)
        return f"Error analyzing {project_id}: {e}", True


async def _check_project(project_id: str, port: int, url: str | None = None) -> tuple[str, bool]:
    """Run browser captures and vision analysis for a project. Returns (findings_text, has_issues)."""
    url = url or await _get_frontend_url(project_id)
    page_paths = _get_page_paths(project_id)
    try:
        captures = await run_browser_captures(project_id, url, page_paths)
    except RuntimeError as e:
        return str(e), True
    if not captures:
        return f"No screenshots captured for {project_id}", True
    return await analyze_captures(project_id, build_user_content(captures, project_id, url))


def _build_findings_prompt(
    result: HealthCheckResult,
    *,
    project_id: str | None = None,
) -> str | None:
    """Build a triage prompt from health check findings, or None if no actionable findings."""
    findings_by_project = result.project_findings
    if project_id is not None:
        findings = findings_by_project.get(project_id)
        findings_by_project = {project_id: findings} if findings is not None else {}

    sections = [
        section
        for project, findings in findings_by_project.items()
        if (section := _build_project_triage_section(project, findings))
    ]
    if not sections:
        return None
    scope_line = (
        f"This wake is scoped to {project_id}."
        if project_id
        else f"{len(sections)} project-specific wake(s) will be dispatched."
    )
    return (
        f"Site health check completed. "
        f"{result.projects_with_issues} project(s) with issues "
        f"out of {result.projects_checked} checked. {scope_line}\n\n"
        f"Review the findings and take action:\n"
        f"- For critical issues: create tasks or dispatch the debugger agent now\n"
        f"- For warnings: create a durable follow-up only if the risk is concrete\n"
        f"- If a tool, permission, or network blocker prevents action, record it once and stop retrying the same path\n\n"
        f"Findings:\n" + "\n\n".join(sections)
    )


async def _wake_persona_with_site_findings(result: HealthCheckResult) -> None:
    """Wake persona agent with site health findings for triage."""
    from app.db import async_session
    from app.services.adaptive_model_router import RoutingContext
    from app.services.agent_routing_utils import resolve_agent
    from app.workflows.persona_wake import WakeInput, agent_wake_task

    async with async_session() as db:
        try:
            resolved = await resolve_agent(
                "persona",
                db,
                RoutingContext(workload_profile="jenny_planning"),
            )
        except Exception:
            logger.warning("Persona agent not found, skipping wake for site health findings")
            return
        agent = resolved.agent
        provider = resolved.provider
    dispatched = 0
    for project_id in result.project_findings:
        prompt = _build_findings_prompt(result, project_id=project_id)
        if not prompt:
            continue
        agent_wake_task.run_no_wait(
            WakeInput(
                agent_slug="persona",
                model=resolved.model,
                provider=provider,
                temperature=agent.temperature,
                prompt=prompt,
                project_id=project_id,
                event_type="site_health_check",
                thinking_level=agent.thinking_level,
            )
        )
        dispatched += 1
    if dispatched > 0:
        logger.info(
            "Persona woken with site health findings (%d issues across %d project wakes)",
            result.projects_with_issues,
            dispatched,
        )


class SingleProjectCheckInput(BaseModel):
    project_id: str
    task_id: str | None = None


async def _poll_service_ready(url: str, attempts: int = 12, interval: float = 5.0) -> bool:
    """Poll a URL until it responds, returning True if ready within the timeout."""
    for _ in range(attempts):
        try:
            await _run_cmd("curl", "-sf", "-o", "/dev/null", url, timeout=5)
            return True
        except Exception:
            await asyncio.sleep(interval)
    return False


@hatchet.task(
    name="single-project-health-check",
    execution_timeout="300s",
    retries=0,
    input_validator=SingleProjectCheckInput,
)
async def single_project_health_check_task(
    input: SingleProjectCheckInput, ctx: Context
) -> dict[str, Any]:
    """On-demand site health check for a single project (post-merge)."""
    project_id = input.project_id
    port = FRONTEND_PORTS.get(project_id)
    if not port:
        return {"status": "skipped", "error": f"Unknown project: {project_id}"}

    url = await _get_frontend_url(project_id)
    if not await _poll_service_ready(url):
        ctx.log(f"Service {project_id} not ready at {url} after 60s")
        return {"status": "error", "error": f"Service not ready: {url}"}

    ctx.log(f"Checking {project_id} at {url}")
    findings, has_issues = await _check_project(project_id, port, url)

    if has_issues:
        result = HealthCheckResult(
            status="issues_found",
            projects_checked=1,
            projects_with_issues=1,
            project_findings={project_id: findings},
        )
        with contextlib.suppress(Exception):
            await _wake_persona_with_site_findings(result)
            ctx.log(f"Persona woken for {project_id} site issues")

    return {
        "status": "issues_found" if has_issues else "healthy",
        "project_id": project_id,
        "task_id": input.task_id,
        "findings": findings[:2000],
    }


@hatchet.task(
    name="site-health-check",
    input_validator=BaseModel,
    on_crons=["30 14 * * 1-5", "0 7 * * *"],  # 2:30pm Mon-Fri + 7am daily
    execution_timeout="900s",
    concurrency=ConcurrencyExpression(
        expression="'site_health_check'",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_IN_PROGRESS,
    ),
)
async def site_health_check_task(input: BaseModel, ctx: Context) -> dict[str, Any]:
    """Scheduled site health check across all frontend projects."""
    from app.services.workflow_schedule_registry import is_workflow_schedule_enabled

    if not await is_workflow_schedule_enabled("site_health_check"):
        ctx.log("Site health check skipped (schedule disabled)")
        return HealthCheckResult(status="disabled").model_dump()

    try:
        project_findings: dict[str, str] = {}
        projects_with_issues = 0

        for project_id, port in FRONTEND_PORTS.items():
            url = await _get_frontend_url(project_id)
            ctx.log(f"Checking {project_id} at {url}")
            findings, has_issues = await _check_project(project_id, port, url)
            project_findings[project_id] = findings
            if has_issues:
                projects_with_issues += 1

        result = HealthCheckResult(
            status="success",
            projects_checked=len(FRONTEND_PORTS),
            projects_with_issues=projects_with_issues,
            project_findings=project_findings,
        )
        ctx.log(f"Site health: {result.projects_checked} checked, {projects_with_issues} with issues")

        if projects_with_issues > 0:
            with contextlib.suppress(Exception):
                await _wake_persona_with_site_findings(result)
                ctx.log("Persona woken for triage")

        return result.model_dump()

    except Exception as e:
        logger.exception("Site health check failed")
        return HealthCheckResult(status="error", error=str(e)).model_dump()
