"""Site health check workflow — proactive frontend monitoring via vision analysis.

Runs on a Hatchet cron schedule (every 4 hours). For each project with a known
frontend port, uses subprocess browser commands to screenshot and collect console
errors, then sends the screenshot to a vision model for analysis. If issues are
found, wakes the persona for triage.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
from pathlib import Path
from typing import Any

from hatchet_sdk import ConcurrencyExpression, ConcurrencyLimitStrategy, Context
from pydantic import BaseModel

from app.hatchet_app import hatchet

logger = logging.getLogger(__name__)

# Project → frontend port mapping (from service port map)
FRONTEND_PORTS: dict[str, int] = {
    "summitflow": 3001,
    "agent-hub": 3003,
    "portfolio-ai": 3000,
    "terminal": 3002,
    "monkey-fight": 4001,
}

CHECK_TIMEOUT_PER_PROJECT = 120  # seconds


class HealthCheckResult(BaseModel):
    status: str
    projects_checked: int = 0
    projects_with_issues: int = 0
    project_findings: dict[str, str] = {}
    error: str | None = None


async def _run_cmd(*args: str, timeout: int = 30) -> str:
    """Run a subprocess command and return stdout. Raises on non-zero exit."""
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(
            f"Command {args} failed (exit {proc.returncode}): "
            f"{stderr.decode().strip()}"
        )
    return stdout.decode().strip()


async def _check_project(project_id: str, port: int) -> tuple[str, bool]:
    """Run browser subprocess commands + vision analysis against a project frontend.

    Phase 1: Subprocess calls to agent-browser (open, wait, screenshot, errors,
             console, snapshot, close).
    Phase 2: Single complete_internal() call with screenshot image + console text.

    Returns (findings_text, has_issues).
    """
    from app.adapters.registry import get_provider_for_model
    from app.api.complete.core import complete_internal
    from app.db import async_session
    from app.services.agent_routing_utils import resolve_agent

    url = f"http://localhost:{port}"

    # Phase 1: Browser subprocess calls
    try:
        await _run_cmd("agent-browser", "open", url)
        await _run_cmd("agent-browser", "wait", "--load", "networkidle", timeout=60)
    except Exception as e:
        with contextlib.suppress(Exception):
            await _run_cmd("agent-browser", "close")
        return f"Failed to load {url}: {e}", True

    screenshot_b64 = ""
    errors_text = ""
    console_text = ""
    snapshot_text = ""

    try:
        # Screenshot
        screenshot_raw = await _run_cmd("agent-browser", "screenshot", "--json")
        try:
            screenshot_data = json.loads(screenshot_raw)
            screenshot_path = screenshot_data.get("data", {}).get("path", "")
        except (json.JSONDecodeError, AttributeError):
            screenshot_path = ""

        if screenshot_path and Path(screenshot_path).exists():
            screenshot_b64 = base64.b64encode(
                Path(screenshot_path).read_bytes()
            ).decode()

        # Console errors
        try:
            errors_text = await _run_cmd("agent-browser", "errors", "--json")
        except Exception:
            errors_text = "No errors captured"

        # Console output
        try:
            console_text = await _run_cmd("agent-browser", "console", "--json")
        except Exception:
            console_text = "No console output captured"

        # Accessibility snapshot (interactive elements only)
        try:
            snapshot_text = await _run_cmd("agent-browser", "snapshot", "-i")
        except Exception:
            snapshot_text = "Snapshot unavailable"

    finally:
        with contextlib.suppress(Exception):
            await _run_cmd("agent-browser", "close")

    # Phase 2: Vision analysis via complete_internal
    if not screenshot_b64:
        return f"No screenshot captured for {project_id}", False

    user_content: list[dict[str, Any]] = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": screenshot_b64,
            },
        },
        {
            "type": "text",
            "text": (
                f"Analyze this screenshot of the {project_id} frontend at {url}.\n\n"
                f"Console errors:\n{errors_text[:2000]}\n\n"
                f"Console output:\n{console_text[:2000]}\n\n"
                f"Accessibility snapshot (interactive elements):\n"
                f"{snapshot_text[:3000]}\n\n"
                "Report each finding with severity (critical/warning/info). "
                "If everything looks healthy, say 'No issues found.'"
            ),
        },
    ]

    try:
        async with async_session() as db:
            resolved = await resolve_agent("site-checker", db)

            # Build model list: primary + fallbacks
            models = [resolved.model]
            fallbacks = resolved.agent.fallback_models or []
            models.extend(fallbacks)

            system_prompt = (
                resolved.agent.system_prompt
                or "Analyze the screenshot and report issues."
            )
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ]

            last_error: Exception | None = None
            for model in models:
                try:
                    provider = get_provider_for_model(model)
                    result = await complete_internal(
                        messages=messages,
                        model=model,
                        provider=provider,
                        temperature=resolved.agent.temperature,
                        project_id=project_id,
                        db=db,
                        agent_slug="site-checker",
                        request_source="site_health_check",
                        use_memory=False,
                        max_turns=1,
                        execute_tools=False,
                        timeout_seconds=60.0,
                    )
                    content = result.content or ""
                    has_issues = any(
                        kw in content.lower()
                        for kw in [
                            "critical",
                            "warning",
                            "error",
                            "broken",
                            "failed to load",
                        ]
                    )
                    return content[:4000], has_issues
                except Exception as e:
                    last_error = e
                    logger.warning(
                        "Model %s failed for %s: %s", model, project_id, e
                    )
                    continue

            return f"All models failed for {project_id}: {last_error}", False

    except Exception as e:
        logger.warning("Site check analysis failed for %s: %s", project_id, e)
        return f"Error analyzing {project_id}: {e}", False


async def _wake_persona_with_site_findings(result: HealthCheckResult) -> None:
    """Wake persona agent with site health findings for triage."""
    from app.db import async_session
    from app.services.agent_routing import get_provider_for_model
    from app.services.agent_service import get_agent_service
    from app.workflows.persona_wake import WakeInput, agent_wake_task

    sections = []
    for project, findings in result.project_findings.items():
        if findings and not findings.startswith("Error"):
            sections.append(f"## {project}\n{findings[:2000]}")

    if not sections:
        return

    findings_text = "\n\n".join(sections)
    prompt = (
        f"Site health check completed. "
        f"{result.projects_with_issues} project(s) with issues "
        f"out of {result.projects_checked} checked.\n\n"
        f"Review the findings and take action:\n"
        f"- For critical issues: create tasks or dispatch the fixer agent\n"
        f"- For warnings: log them and monitor\n"
        f"- For info items: note in journal if patterns emerge\n\n"
        f"Findings:\n{findings_text}"
    )

    async with async_session() as db:
        agent_service = get_agent_service()
        agent = await agent_service.get_by_slug(db, "persona")
        if not agent:
            logger.warning("Persona agent not found, skipping wake for site health findings")
            return
        provider = get_provider_for_model(agent.primary_model_id)

    wake_input = WakeInput(
        agent_slug="persona",
        model=agent.primary_model_id,
        provider=provider,
        temperature=agent.temperature,
        prompt=prompt,
        project_id="agent-hub",
        event_type="site_health_check",
        thinking_level=agent.thinking_level,
    )
    agent_wake_task.run_no_wait(wake_input)
    logger.info("Persona woken with site health findings (%d issues)", result.projects_with_issues)


@hatchet.task(
    name="site-health-check",
    input_validator=BaseModel,
    on_crons=["0 */4 * * *"],  # Every 4 hours
    execution_timeout="900s",  # 15 min total
    concurrency=ConcurrencyExpression(
        expression="'site_health_check'",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_IN_PROGRESS,
    ),
)
async def site_health_check_task(input: BaseModel, ctx: Context) -> dict[str, Any]:
    """Scheduled site health check across all frontend projects."""
    try:
        project_findings: dict[str, str] = {}
        projects_with_issues = 0

        for project_id, port in FRONTEND_PORTS.items():
            ctx.log(f"Checking {project_id} at localhost:{port}")
            findings, has_issues = await _check_project(project_id, port)
            project_findings[project_id] = findings
            if has_issues:
                projects_with_issues += 1

        result = HealthCheckResult(
            status="success",
            projects_checked=len(FRONTEND_PORTS),
            projects_with_issues=projects_with_issues,
            project_findings=project_findings,
        )

        ctx.log(
            f"Site health: {result.projects_checked} checked, "
            f"{projects_with_issues} with issues"
        )

        if projects_with_issues > 0:
            try:
                await _wake_persona_with_site_findings(result)
                ctx.log("Persona woken for triage")
            except Exception as e:
                logger.warning("Failed to wake persona with site findings: %s", e)

        return result.model_dump()

    except Exception as e:
        logger.exception("Site health check failed")
        return HealthCheckResult(status="error", error=str(e)).model_dump()
