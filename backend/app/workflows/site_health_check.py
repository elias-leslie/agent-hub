"""Site health check workflow — proactive frontend monitoring via site-checker agent.

Runs on a Hatchet cron schedule (every 4 hours). For each project with a known
frontend port, dispatches the site-checker agent to browse, screenshot, and
evaluate the frontend. If issues are found, wakes the persona for triage.
"""

from __future__ import annotations

import logging
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


async def _check_project(project_id: str, port: int) -> tuple[str, bool]:
    """Run site-checker agent against a single project's frontend.

    Returns (findings_text, has_issues).
    """
    from app.api.complete.core import complete_internal
    from app.db import async_session
    from app.services.agent_routing_utils import inject_agent_mandates, resolve_agent

    url = f"http://localhost:{port}"
    prompt = (
        f"Check the {project_id} frontend at {url} for health issues.\n\n"
        f"1. Open {url} and wait for it to load\n"
        f"2. Take a screenshot and evaluate the visual state\n"
        f"3. Check for console errors and warnings\n"
        f"4. Navigate to 2-3 key pages/sections if applicable\n"
        f"5. Report any issues found with severity levels\n"
        f"6. Close the browser when done\n\n"
        f"If the page fails to load, report it as critical and stop."
    )

    try:
        async with async_session() as db:
            resolved = await resolve_agent("site-checker", db)
            mandate = await inject_agent_mandates(
                resolved.agent, db, prompt_mode="minimal",
                project_id=project_id,
            )
            messages: list[dict[str, str]] = []
            if mandate.system_content:
                messages.append({"role": "system", "content": mandate.system_content})
            messages.append({"role": "user", "content": prompt})

            result = await complete_internal(
                messages=messages,
                model=resolved.model,
                provider=resolved.provider,
                temperature=resolved.agent.temperature,
                project_id=project_id,
                db=db,
                agent_slug="site-checker",
                request_source="site_health_check",
                use_memory=True,
                memory_group_id=f"project-{project_id}",
                max_turns=15,
                execute_tools=True,
                timeout_seconds=float(CHECK_TIMEOUT_PER_PROJECT),
            )

        content = result.content or ""
        has_issues = any(
            keyword in content.lower()
            for keyword in ["critical", "warning", "error", "broken", "failed to load"]
        )
        return content[:4000], has_issues

    except Exception as e:
        logger.warning("Site check failed for %s: %s", project_id, e)
        return f"Error checking {project_id}: {e}", False


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
