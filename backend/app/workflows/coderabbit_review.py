"""CodeRabbit daily review — runs reviews across projects, wakes persona with findings.

Runs CodeRabbit CLI directly via subprocess (no LLM needed for the mechanical part),
collects findings, then wakes the persona agent with results for triage and bug filing.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
from pathlib import Path
from typing import Any

from hatchet_sdk import ConcurrencyExpression, ConcurrencyLimitStrategy, Context
from pydantic import BaseModel

from app.core.project_roots import resolve_project_root
from app.hatchet_app import hatchet

logger = logging.getLogger(__name__)

REVIEW_PROJECT_IDS = (
    "summitflow",
    "agent-hub",
    "aterm",
    "portfolio-ai",
    "monkey-fight",
)

SHA_MARKER = ".dev-tools/coderabbit-last-reviewed.sha"
REVIEW_TIMEOUT_PER_PROJECT = 300  # 5 min


class ReviewResult(BaseModel):
    status: str
    projects_reviewed: int = 0
    total_findings: int = 0
    project_summaries: dict[str, str] = {}
    error: str | None = None


def _get_last_sha(project_path: Path) -> str | None:
    """Read last reviewed SHA from marker file."""
    marker = project_path / SHA_MARKER
    if marker.is_file():
        sha = marker.read_text().strip()
        return sha or None
    return None


def _update_sha(project_path: Path) -> None:
    """Write current HEAD to marker file."""
    marker = project_path / SHA_MARKER
    marker.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project_path,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        marker.write_text(result.stdout.strip())


def _count_findings(output: str) -> int:
    """Count CodeRabbit findings from review output."""
    return sum(1 for line in output.splitlines() if line.startswith("Type:"))


def _run_review(project_name: str, project_path: Path) -> tuple[str, int]:
    """Run CodeRabbit review for a single project.

    Returns (findings_text, finding_count).
    """
    if not project_path.is_dir():
        return f"Skipped: {project_path} does not exist", 0

    last_sha = _get_last_sha(project_path)

    # If last_sha == HEAD, no new commits to review
    if last_sha:
        head_result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_path,
            capture_output=True,
            text=True,
        )
        if head_result.returncode == 0 and head_result.stdout.strip() == last_sha:
            return "Skipped: no new commits since last review", 0

    cmd = ["coderabbit", "review", "--plain"]
    if last_sha:
        cmd += ["--type", "committed", "--base-commit", last_sha]
    else:
        # First run — review last 10 commits
        result = subprocess.run(
            ["git", "rev-parse", "HEAD~10"],
            cwd=project_path,
            capture_output=True,
            text=True,
        )
        base = result.stdout.strip() if result.returncode == 0 else None
        if base:
            cmd += ["--type", "committed", "--base-commit", base]

    try:
        proc = subprocess.run(
            cmd,
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=REVIEW_TIMEOUT_PER_PROJECT,
        )
        output = (proc.stdout + proc.stderr).strip()

        if "rate limit" in output.lower() or "429" in output:
            return "Skipped: rate limited", 0

        # Update SHA marker after review completes (regardless of findings)
        _update_sha(project_path)

        finding_count = _count_findings(output)

        if proc.returncode == 0 and finding_count == 0:
            return "Clean — no findings", 0

        return output[:4000], finding_count

    except subprocess.TimeoutExpired:
        return "Skipped: timeout", 0
    except FileNotFoundError:
        return "Error: coderabbit CLI not found at expected path", 0
    except Exception as e:
        return f"Error: {e}", 0


async def run_all_reviews() -> ReviewResult:
    """Run CodeRabbit reviews across all projects sequentially."""
    loop = asyncio.get_running_loop()

    project_summaries: dict[str, str] = {}
    total_findings = 0
    projects_reviewed = 0

    for name in REVIEW_PROJECT_IDS:
        path = resolve_project_root(name) or Path(f"/missing/{name}")
        findings, count = await loop.run_in_executor(
            None, _run_review, name, path,
        )
        project_summaries[name] = findings
        total_findings += count
        if not findings.startswith(("Skipped", "Error")):
            projects_reviewed += 1

    return ReviewResult(
        status="success",
        projects_reviewed=projects_reviewed,
        total_findings=total_findings,
        project_summaries=project_summaries,
    )


async def _wake_persona_with_findings(result: ReviewResult) -> None:
    """Wake persona agent with findings for triage and bug filing."""
    from app.db import async_session
    from app.services.agent_routing import get_provider_for_model
    from app.services.agent_service import get_agent_service
    from app.workflows.persona_wake import WakeInput, agent_wake_task

    # Build findings summary — only include projects with actual findings
    sections = []
    for project, findings in result.project_summaries.items():
        if findings not in ("Clean — no findings",) and not findings.startswith(("Skipped", "Error")):
            sections.append(f"## {project}\n```\n{findings[:2000]}\n```")

    if not sections:
        return

    findings_text = "\n\n".join(sections)

    prompt = (
        f"CodeRabbit daily review completed. "
        f"{result.total_findings} finding(s) across {result.projects_reviewed} project(s).\n\n"
        f"Review the findings below and take action:\n"
        f"- For real bugs or issues: create tasks with `manage_tasks` (action=create)\n"
        f"- Skip false positives (unused import suggestions for re-exports, minor style nits)\n"
        f"- Journal notable patterns or recurring issues\n\n"
        f"Findings:\n{findings_text}"
    )

    async with async_session() as db:
        agent_service = get_agent_service()
        agent = await agent_service.get_by_slug(db, "persona")
        if not agent:
            logger.warning("Persona agent not found, skipping wake for CodeRabbit findings")
            return
        provider = get_provider_for_model(agent.primary_model_id)

    wake_input = WakeInput(
        agent_slug="persona",
        model=agent.primary_model_id,
        provider=provider,
        temperature=agent.temperature,
        prompt=prompt,
        project_id="summitflow",
        event_type="coderabbit_review",
        thinking_level=agent.thinking_level,
    )
    await agent_wake_task.aio_run_no_wait(input=wake_input)
    logger.info("Persona woken with %d CodeRabbit findings for triage", result.total_findings)


@hatchet.task(
    name="coderabbit-daily-review",
    input_validator=BaseModel,
    on_crons=["0 19 * * *"],  # 2pm ET = 7pm UTC
    execution_timeout="1800s",  # 30 min total
    concurrency=ConcurrencyExpression(
        expression="'coderabbit_review'",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_IN_PROGRESS,
    ),
)
async def coderabbit_daily_review_task(input: BaseModel, ctx: Context) -> dict[str, Any]:
    """Daily CodeRabbit review across all projects."""
    try:
        result = await run_all_reviews()

        ctx.log(
            f"CodeRabbit: {result.projects_reviewed} projects reviewed, "
            f"{result.total_findings} findings"
        )

        if result.total_findings > 0:
            try:
                await _wake_persona_with_findings(result)
                ctx.log("Persona woken for triage")
            except Exception as e:
                logger.warning("Failed to wake persona with findings: %s", e)

        return result.model_dump()

    except Exception as e:
        logger.exception("CodeRabbit daily review failed")
        return ReviewResult(status="error", error=str(e)).model_dump()
