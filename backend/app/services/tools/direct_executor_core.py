"""Core executor implementation for direct tool execution.

Handles bash command execution, file I/O, and agent consultation with
proper environment inheritance.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import ClassVar

from app.services.tools.project_env import build_project_env
from app.services.tools.registry import get_command_redirect

logger = logging.getLogger(__name__)

# Maximum output size to return
MAX_OUTPUT_SIZE = 100_000

# Default timeout for commands
DEFAULT_TIMEOUT = 120

# Blocked commands for safety (destructive system commands)
BLOCKED_COMMANDS = frozenset(
    {
        "rm -rf /",
        "rm -rf /*",
        "mkfs",
        "dd if=/dev/zero",
        "> /dev/sda",
        # Git safety — agents must use st CLI for task work
        "git push --force",
        "git push -f",
        "git reset --hard",
        "git clean -fd",
        "git clean -f",
        "git checkout .",
        # Service safety — agents must use wrapper scripts
        "systemctl stop",
        "systemctl disable",
        "drop database",
        "drop table",
        "truncate",
    }
)


def _is_blocked_command(command: str) -> bool:
    """Check if command is blocked for safety."""
    command_lower = command.lower().strip()
    return any(blocked in command_lower for blocked in BLOCKED_COMMANDS)


def _get_command_redirect(command: str) -> str | None:
    """Check if command should be redirected to a standardized wrapper.

    Delegates to the centralized tool registry (tool-registry.json).
    Returns redirect message if command should use dt/st/restart scripts,
    None if the command is allowed to proceed.
    """
    return get_command_redirect(command)


class DirectToolExecutor:
    """Executes tools directly with environment inheritance.

    All operations run in the specified working directory with full
    access to the parent process environment variables.
    """

    def __init__(self, working_dir: str | None = None, project_id: str | None = None):
        """Initialize with working directory.

        Resolves the project's Python venv once at init. Handles worktrees
        by detecting the main repo and using its venv. All subprocess calls
        use this resolved environment.

        Args:
            working_dir: Base directory for all operations. Defaults to current dir.
            project_id: Project ID for agent consultation (enables consult_agent tool).
        """
        self.working_dir = Path(working_dir or ".").resolve()
        if not self.working_dir.exists():
            self.working_dir.mkdir(parents=True, exist_ok=True)
        self._env = build_project_env(self.working_dir)
        self._project_id = project_id
        self._allowed_root: Path | None = self._resolve_project_root(project_id)

    @staticmethod
    def _resolve_project_root(project_id: str | None) -> Path | None:
        """Resolve the allowed root path for a project from the cache/DB.

        Returns None if no restriction applies (no project_id or unknown project).
        """
        if not project_id:
            return None
        try:
            import json

            import redis

            from app.config import settings

            r = redis.from_url(settings.agent_hub_redis_url, decode_responses=True)
            # Quick check — we also stored root_path at seed time, but the
            # cache only stores tier+auto_exec. Use a direct DB lookup instead.
            r.close()
        except Exception:
            pass
        # Use known root paths from constants (fast, no I/O)
        _KNOWN_ROOTS: dict[str, str] = {
            "summitflow": "/home/kasadis/summitflow",
            "agent-hub": "/home/kasadis/agent-hub",
            "portfolio-ai": "/home/kasadis/portfolio-ai",
            "terminal": "/home/kasadis/terminal",
            "monkey-fight": "/home/kasadis/monkey-fight",
        }
        root = _KNOWN_ROOTS.get(project_id)
        return Path(root) if root else None

    def _is_path_allowed(self, path: Path) -> bool:
        """Check if a resolved path is within the project's allowed root.

        Returns True if no root restriction or path is within root.
        """
        if not self._allowed_root:
            return True
        try:
            path.resolve().relative_to(self._allowed_root)
            return True
        except ValueError:
            return False

    async def bash(self, command: str, timeout: int = DEFAULT_TIMEOUT) -> str:
        """Execute a bash command with environment inheritance.

        Args:
            command: The command to execute
            timeout: Timeout in seconds (default 120)

        Returns:
            Command output (stdout + stderr)
        """
        if _is_blocked_command(command):
            return f"Error: Command blocked for safety: {command}"

        redirect = _get_command_redirect(command)
        if redirect:
            return f"Error: Command redirected. {redirect}"

        # Best-effort working directory enforcement
        if self._allowed_root and not self._is_path_allowed(self.working_dir):
            return f"Error: Working directory outside allowed project root"

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.working_dir),
                env=self._env,
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout,
            )

            output = stdout.decode("utf-8", errors="replace")
            stderr_text = stderr.decode("utf-8", errors="replace")

            # Combine stdout and stderr
            if stderr_text:
                output = output + stderr_text

            if len(output) > MAX_OUTPUT_SIZE:
                output = output[:MAX_OUTPUT_SIZE] + "\n... (output truncated)"

            return output or "(no output)"

        except TimeoutError:
            return f"Error: Command timed out after {timeout}s"
        except Exception as e:
            return f"Error executing command: {e}"

    async def read_file(self, path: str, offset: int = 0, limit: int = 2000) -> str:
        """Read a file.

        Args:
            path: File path (absolute or relative to working dir)
            offset: Line offset (0-indexed)
            limit: Max lines to read

        Returns:
            File contents with line numbers
        """
        file_path = Path(path)
        if not file_path.is_absolute():
            file_path = (self.working_dir / path).resolve()

        if not self._is_path_allowed(file_path):
            return f"Error: Path outside allowed project root: {path}"

        if not file_path.exists():
            return f"Error: File not found: {path}"
        if file_path.is_dir():
            return f"Error: Path is a directory: {path}"

        try:
            with open(file_path, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()

            total_lines = len(lines)
            selected = lines[offset : offset + limit]

            # Format with line numbers
            result_lines = []
            for i, line in enumerate(selected, start=offset + 1):
                result_lines.append(f"{i:6}\t{line.rstrip()}")

            result = "\n".join(result_lines)

            if offset + limit < total_lines:
                result += f"\n... ({total_lines - offset - limit} more lines)"

            return result or "(empty file)"

        except Exception as e:
            return f"Error reading file: {e}"

    async def write_file(self, path: str, content: str) -> str:
        """Write a file.

        Args:
            path: File path (absolute or relative to working dir)
            content: File content

        Returns:
            Success or error message
        """
        file_path = Path(path)
        if not file_path.is_absolute():
            file_path = (self.working_dir / path).resolve()

        if not self._is_path_allowed(file_path):
            return f"Error: Path outside allowed project root: {path}"

        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"Successfully wrote {len(content)} bytes to {path}"
        except Exception as e:
            return f"Error writing file: {e}"

    async def consult_agent(self, agent_slug: str, question: str, context: str = "") -> str:
        """Consult another agent for advice without executing tools.

        Makes a direct in-process call to complete_internal() to avoid
        HTTP self-call deadlock with single uvicorn worker.

        Args:
            agent_slug: Agent to consult (e.g., 'supervisor', 'reviewer')
            question: The question or problem description
            context: Optional additional context about the current situation

        Returns:
            The consulted agent's response text
        """
        if not self._project_id:
            return "Error: project_id not configured, cannot consult agent"

        prompt = question
        if context:
            prompt = f"Context:\n{context}\n\nQuestion:\n{question}"

        try:
            from app.api.complete.core import complete_internal
            from app.db import async_session
            from app.services.agent_routing_utils import inject_agent_mandates, resolve_agent

            async with async_session() as db:
                resolved = await resolve_agent(agent_slug, db)

                # Inject system prompt with minimal mode (sub-agent call)
                mandate = await inject_agent_mandates(
                    resolved.agent, db, prompt_mode="minimal"
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
                    project_id=self._project_id,
                    db=db,
                    agent_slug=agent_slug,
                    request_source="consultation",
                    use_memory=True,
                    memory_group_id=f"project-{self._project_id}",
                    max_turns=1,
                    execute_tools=False,
                )
                session_id = result.session_id if hasattr(result, "session_id") else None
                content = result.content
                if session_id:
                    return f"[session:{session_id}] {content}"
                return content
        except Exception as e:
            logger.exception(f"consult_agent failed for '{agent_slug}'")
            return f"Error consulting agent '{agent_slug}': {e}"

    async def read_personality(self) -> str:
        """Read the persona's current personality document.

        Returns:
            The personality text, or a message if none is set.
        """
        try:
            from app.db import async_session
            from app.services.persona_service import get_or_create_persona

            async with async_session() as db:
                persona = await get_or_create_persona(db)
                if persona.personality:
                    return persona.personality
                return "(No personality document set. Use write_personality to create one.)"
        except Exception as e:
            logger.exception("read_personality failed")
            return f"Error reading personality: {e}"

    async def write_personality(self, personality: str, reason: str) -> str:
        """Update the persona's personality document.

        Args:
            personality: The new personality document (markdown)
            reason: Why the personality is being updated

        Returns:
            Confirmation message
        """
        try:
            from app.db import async_session
            from app.services.persona_service import get_or_create_persona

            async with async_session() as db:
                persona = await get_or_create_persona(db)
                persona.personality = personality
                persona.version += 1
                await db.commit()

            return f"Personality updated (version {persona.version}). Reason: {reason}"
        except Exception as e:
            logger.exception("write_personality failed")
            return f"Error writing personality: {e}"

    _VALID_ENTRY_TYPES: ClassVar[set[str]] = {"observation", "decision", "learning", "user_insight"}

    async def write_journal(self, content: str, entry_type: str = "observation") -> str:
        """Write a journal entry for today.

        Args:
            content: The journal entry content
            entry_type: observation, decision, learning, or user_insight

        Returns:
            Confirmation message
        """
        if entry_type not in self._VALID_ENTRY_TYPES:
            return (
                f"Invalid entry_type '{entry_type}'. "
                f"Must be one of: {', '.join(sorted(self._VALID_ENTRY_TYPES))}"
            )
        try:
            from app.db import async_session
            from app.models.persona_journal import PersonaJournal
            from app.services.persona_service import get_or_create_persona

            async with async_session() as db:
                persona = await get_or_create_persona(db)
                entry = PersonaJournal(
                    persona_id=persona.id,
                    content=content,
                    entry_type=entry_type,
                )
                db.add(entry)
                await db.commit()

            return f"Journal entry recorded ({entry_type})"
        except Exception as e:
            logger.exception("write_journal failed")
            return f"Error writing journal: {e}"

    async def read_journal(self, days_back: int = 7) -> str:
        """Read recent journal entries.

        Args:
            days_back: How many days to look back (default 7)

        Returns:
            Formatted journal entries
        """
        try:
            from datetime import date, timedelta

            from sqlalchemy import select

            from app.db import async_session
            from app.models.persona_journal import PersonaJournal
            from app.services.persona_service import get_or_create_persona

            since = date.today() - timedelta(days=days_back)

            async with async_session() as db:
                persona = await get_or_create_persona(db)
                result = await db.execute(
                    select(PersonaJournal)
                    .where(
                        PersonaJournal.persona_id == persona.id,
                        PersonaJournal.entry_date >= since,
                    )
                    .order_by(PersonaJournal.entry_date.desc(), PersonaJournal.created_at.desc())
                )
                entries = result.scalars().all()

            if not entries:
                return f"(No journal entries in the last {days_back} days)"

            lines = []
            for entry in entries:
                lines.append(f"## {entry.entry_date} [{entry.entry_type}]")
                lines.append(entry.content)
                lines.append("")

            return "\n".join(lines)
        except Exception as e:
            logger.exception("read_journal failed")
            return f"Error reading journal: {e}"

    async def search_journal(self, query: str, days_back: int = 30) -> str:
        """Search journal entries by content.

        Args:
            query: Text to search for
            days_back: How many days back to search (default 30)

        Returns:
            Matching journal entries
        """
        try:
            from datetime import date, timedelta

            from sqlalchemy import select

            from app.db import async_session
            from app.models.persona_journal import PersonaJournal
            from app.services.persona_service import get_or_create_persona

            since = date.today() - timedelta(days=days_back)

            async with async_session() as db:
                persona = await get_or_create_persona(db)
                result = await db.execute(
                    select(PersonaJournal)
                    .where(
                        PersonaJournal.persona_id == persona.id,
                        PersonaJournal.entry_date >= since,
                        PersonaJournal.content.ilike(f"%{query}%"),
                    )
                    .order_by(PersonaJournal.entry_date.desc(), PersonaJournal.created_at.desc())
                )
                entries = result.scalars().all()

            if not entries:
                return f"(No journal entries matching '{query}' in the last {days_back} days)"

            lines = []
            for entry in entries:
                lines.append(f"## {entry.entry_date} [{entry.entry_type}]")
                lines.append(entry.content)
                lines.append("")

            return "\n".join(lines)
        except Exception as e:
            logger.exception("search_journal failed")
            return f"Error searching journal: {e}"

    async def write_user_context(self, user_context: str) -> str:
        """Update the persona's user context document.

        Args:
            user_context: The updated user context (markdown)

        Returns:
            Confirmation message
        """
        try:
            from app.db import async_session
            from app.services.persona_service import get_or_create_persona

            async with async_session() as db:
                persona = await get_or_create_persona(db)
                persona.user_context = user_context
                persona.version += 1
                await db.commit()

            return "User context updated"
        except Exception as e:
            logger.exception("write_user_context failed")
            return f"Error writing user context: {e}"

    async def read_user_context(self) -> str:
        """Read the persona's current user context.

        Returns:
            The user context text, or a message if none is set.
        """
        try:
            from app.db import async_session
            from app.services.persona_service import get_or_create_persona

            async with async_session() as db:
                persona = await get_or_create_persona(db)
                if persona.user_context:
                    return persona.user_context
                return "(No user context set. Use write_user_context to record what you learn about the user.)"
        except Exception as e:
            logger.exception("read_user_context failed")
            return f"Error reading user context: {e}"

    async def mark_memory_relevant(self, memory_uuid: str) -> str:
        """Add 'persona-relevant' tag to a memory episode.

        Args:
            memory_uuid: UUID of the episode

        Returns:
            Confirmation message
        """
        try:
            from app.services.memory.episode_property_queries import get_episode_tags
            from app.services.memory.episode_property_setters import set_episode_tags

            current_tags = await get_episode_tags(memory_uuid)
            tag = "persona-relevant"
            if tag in current_tags:
                return f"Memory {memory_uuid[:8]} already tagged as persona-relevant"

            current_tags.append(tag)
            success = await set_episode_tags(memory_uuid, current_tags)
            if success:
                return f"Memory {memory_uuid[:8]} marked as persona-relevant"
            return f"Failed to tag memory {memory_uuid[:8]}"
        except Exception as e:
            logger.exception("mark_memory_relevant failed")
            return f"Error marking memory relevant: {e}"

    async def mark_memory_irrelevant(self, memory_uuid: str) -> str:
        """Remove 'persona-relevant' tag from a memory episode.

        Args:
            memory_uuid: UUID of the episode

        Returns:
            Confirmation message
        """
        try:
            from app.services.memory.episode_property_queries import get_episode_tags
            from app.services.memory.episode_property_setters import set_episode_tags

            current_tags = await get_episode_tags(memory_uuid)
            tag = "persona-relevant"
            if tag not in current_tags:
                return f"Memory {memory_uuid[:8]} is not tagged as persona-relevant"

            current_tags.remove(tag)
            success = await set_episode_tags(memory_uuid, current_tags)
            if success:
                return f"Removed persona-relevant tag from memory {memory_uuid[:8]}"
            return f"Failed to update tags for memory {memory_uuid[:8]}"
        except Exception as e:
            logger.exception("mark_memory_irrelevant failed")
            return f"Error marking memory irrelevant: {e}"

    async def submit_onboarding(self, summary: str) -> str:
        """Submit the onboarding profile for dual-model approval.

        Args:
            summary: Comprehensive summary of onboarding answers

        Returns:
            Approval confirmation or rejection feedback
        """
        try:
            from app.db import async_session
            from app.services.persona_service import (
                get_or_create_persona,
                submit_and_review_onboarding,
            )

            async with async_session() as db:
                persona = await get_or_create_persona(db)
                user_context_snapshot = persona.user_context

                result = await submit_and_review_onboarding(
                    db, summary, user_context_snapshot,
                )

            if result["status"] == "approved":
                return (
                    "Onboarding APPROVED by both reviewers. You're fully operational now.\n\n"
                    f"Reviewer feedback:\n{result['feedback']}"
                )
            return (
                "Onboarding REJECTED — needs revision. Review the feedback below and "
                "follow up with the user on the gaps.\n\n"
                f"Reviewer feedback:\n{result['feedback']}"
            )
        except Exception as e:
            logger.exception("submit_onboarding failed")
            return f"Error submitting onboarding: {e}"

    async def send_push(
        self,
        title: str,
        body: str,
        url: str | None = None,
        severity: str = "info",
        tag: str | None = None,
    ) -> str:
        """Send a push notification to all subscribed devices.

        Args:
            title: Notification title
            body: Notification body text
            url: Optional deep-link URL
            severity: info/warning/error/critical
            tag: Optional dedup tag

        Returns:
            Success message with delivery count
        """
        try:
            from app.db import async_session
            from app.services.push_service import send_push as _send_push

            payload: dict[str, str | None] = {
                "title": title,
                "body": body,
            }
            if url:
                payload["url"] = url
            if severity:
                payload["severity"] = severity
            if tag:
                payload["tag"] = tag

            async with async_session() as db:
                sent = await _send_push(db, payload=payload)

            return f"Push notification sent to {sent} device(s): {title}"
        except Exception as e:
            logger.exception("send_push failed")
            return f"Error sending push notification: {e}"

    # -----------------------------------------------------------------------
    # Scheduling tools
    # -----------------------------------------------------------------------

    async def schedule_job(
        self,
        name: str,
        schedule_type: str,
        schedule_value: str,
        payload_message: str,
        payload_type: str = "agent_turn",
        delivery: str = "none",
        timezone: str = "UTC",
    ) -> str:
        """Create a scheduled job for the persona.

        Args:
            name: Human-readable job name
            schedule_type: "at", "every", or "cron"
            schedule_value: ISO datetime, interval ms, or cron expression
            payload_message: Message to inject or push body
            payload_type: "agent_turn" or "push"
            delivery: "none" or "push"
            timezone: IANA timezone for cron scheduling

        Returns:
            Confirmation with job ID and next_run_at
        """
        if schedule_type not in ("at", "every", "cron"):
            return f"Error: Invalid schedule_type '{schedule_type}'. Must be at/every/cron."

        try:
            from app.db import async_session
            from app.models.persona_scheduled_job import PersonaScheduledJob
            from app.services.persona_service import get_or_create_persona, get_persona_limit
            from app.workflows.persona_scheduler import compute_next_run

            async with async_session() as db:
                persona = await get_or_create_persona(db)

                # Check job limit
                from sqlalchemy import func, select

                count_result = await db.execute(
                    select(func.count()).select_from(PersonaScheduledJob).where(
                        PersonaScheduledJob.persona_id == persona.id,
                        PersonaScheduledJob.enabled.is_(True),
                    )
                )
                active_count = count_result.scalar() or 0
                max_jobs = get_persona_limit(persona, "max_scheduled_jobs")
                if active_count >= max_jobs:
                    return f"Error: Maximum active jobs ({max_jobs}) reached. Cancel some first."

                # Compute initial next_run_at
                next_run = compute_next_run(schedule_type, schedule_value, timezone)
                if next_run is None and schedule_type == "at":
                    return "Error: Scheduled time is in the past."

                max_runs = 1 if schedule_type == "at" else None

                job = PersonaScheduledJob(
                    persona_id=persona.id,
                    name=name,
                    schedule_type=schedule_type,
                    schedule_value=schedule_value,
                    schedule_timezone=timezone,
                    payload_type=payload_type,
                    payload_message=payload_message,
                    delivery=delivery,
                    next_run_at=next_run,
                    max_runs=max_runs,
                )
                db.add(job)
                await db.commit()
                await db.refresh(job)

            next_str = next_run.isoformat() if next_run else "N/A"
            return f"Job '{name}' scheduled (id={job.id}). Next run: {next_str}"
        except Exception as e:
            logger.exception("schedule_job failed")
            return f"Error scheduling job: {e}"

    async def list_scheduled_jobs(self, include_disabled: bool = False) -> str:
        """List scheduled jobs for the persona.

        Args:
            include_disabled: Include disabled/completed jobs

        Returns:
            Formatted list of jobs
        """
        try:
            from sqlalchemy import select

            from app.db import async_session
            from app.models.persona_scheduled_job import PersonaScheduledJob
            from app.services.persona_service import get_or_create_persona

            async with async_session() as db:
                persona = await get_or_create_persona(db)
                query = select(PersonaScheduledJob).where(
                    PersonaScheduledJob.persona_id == persona.id
                )
                if not include_disabled:
                    query = query.where(PersonaScheduledJob.enabled.is_(True))
                query = query.order_by(PersonaScheduledJob.next_run_at)

                result = await db.execute(query)
                jobs = result.scalars().all()

            if not jobs:
                return "(No scheduled jobs)"

            lines = []
            for job in jobs:
                status = "enabled" if job.enabled else "disabled"
                next_str = job.next_run_at.isoformat() if job.next_run_at else "N/A"
                runs = f"{job.run_count}"
                if job.max_runs:
                    runs += f"/{job.max_runs}"
                lines.append(
                    f"- **{job.name}** (id={job.id})\n"
                    f"  {job.schedule_type}={job.schedule_value} | "
                    f"next={next_str} | runs={runs} | {status}"
                )

            return "\n".join(lines)
        except Exception as e:
            logger.exception("list_scheduled_jobs failed")
            return f"Error listing jobs: {e}"

    async def cancel_scheduled_job(
        self, job_id: str, hard_delete: bool = False,
    ) -> str:
        """Disable or delete a scheduled job.

        Args:
            job_id: UUID of the job
            hard_delete: Permanently delete if True, just disable if False

        Returns:
            Confirmation message
        """
        try:
            from sqlalchemy import select

            from app.db import async_session
            from app.models.persona_scheduled_job import PersonaScheduledJob

            async with async_session() as db:
                result = await db.execute(
                    select(PersonaScheduledJob).where(PersonaScheduledJob.id == job_id)
                )
                job = result.scalar_one_or_none()
                if not job:
                    return f"Error: Job '{job_id}' not found."

                name = job.name
                if hard_delete:
                    await db.delete(job)
                    await db.commit()
                    return f"Job '{name}' (id={job_id}) permanently deleted."

                job.enabled = False
                await db.commit()
                return f"Job '{name}' (id={job_id}) disabled."
        except Exception as e:
            logger.exception("cancel_scheduled_job failed")
            return f"Error cancelling job: {e}"

    # -----------------------------------------------------------------------
    # Subagent steering tools
    # -----------------------------------------------------------------------

    async def steer_consultation(self, session_id: str, message: str) -> str:
        """Send a follow-up message to an existing consultation session.

        Args:
            session_id: Session ID from a previous consult_agent response
            message: Follow-up message

        Returns:
            The consulted agent's response
        """
        if not self._project_id:
            return "Error: project_id not configured"

        try:
            import redis.asyncio as redis

            from app.api.complete.core import complete_internal
            from app.config import settings
            from app.db import async_session
            from app.services.persona_service import get_persona, get_persona_limit

            # Rate limit check
            redis_client = redis.from_url(
                settings.agent_hub_redis_url, encoding="utf-8", decode_responses=True,
            )
            try:
                counter_key = f"consultation:steers:{session_id}"
                count = await redis_client.incr(counter_key)
                if count == 1:
                    await redis_client.expire(counter_key, 3600)

                async with async_session() as db:
                    persona = await get_persona(db)
                max_steers = get_persona_limit(persona, "max_steers_per_consultation")
                if count > max_steers:
                    return (
                        f"Error: Rate limit reached ({max_steers} steers per consultation session). "
                        "Start a new consultation with consult_agent."
                    )
            finally:
                await redis_client.close()

            async with async_session() as db:
                result = await complete_internal(
                    messages=[{"role": "user", "content": message}],
                    model="claude-haiku-4-5",
                    provider="claude",
                    temperature=0.3,
                    project_id=self._project_id,
                    db=db,
                    session_id=session_id,
                    request_source="consultation",
                    max_turns=1,
                    execute_tools=False,
                )
                return f"[session:{session_id}] {result.content}"
        except Exception as e:
            logger.exception("steer_consultation failed")
            return f"Error steering consultation: {e}"

    async def list_consultations(
        self, hours_back: int = 24, agent_slug: str | None = None,
    ) -> str:
        """List recent consultation sessions.

        Args:
            hours_back: How many hours back to look
            agent_slug: Optional filter by agent slug

        Returns:
            Formatted list of consultations
        """
        try:
            from datetime import UTC, datetime, timedelta

            from sqlalchemy import select

            from app.db import async_session
            from app.models import Session as DBSession

            cutoff = datetime.now(UTC) - timedelta(hours=hours_back)

            async with async_session() as db:
                query = (
                    select(DBSession)
                    .where(
                        DBSession.request_source == "consultation",
                        DBSession.created_at >= cutoff,
                    )
                    .order_by(DBSession.created_at.desc())
                    .limit(50)
                )
                if agent_slug:
                    query = query.where(DBSession.agent_slug == agent_slug)

                result = await db.execute(query)
                sessions = result.scalars().all()

            if not sessions:
                return f"(No consultations in the last {hours_back} hours)"

            lines = []
            for s in sessions:
                created = s.created_at.strftime("%Y-%m-%d %H:%M") if s.created_at else "?"
                lines.append(
                    f"- {s.agent_slug or '?'} | session={s.id} | "
                    f"status={s.status} | created={created}"
                )

            return "\n".join(lines)
        except Exception as e:
            logger.exception("list_consultations failed")
            return f"Error listing consultations: {e}"

    async def cancel_consultation(self, session_id: str) -> str:
        """Close a running consultation session.

        Args:
            session_id: Session ID to close

        Returns:
            Confirmation message
        """
        try:
            from sqlalchemy import select

            from app.db import async_session
            from app.models import Session as DBSession

            async with async_session() as db:
                result = await db.execute(
                    select(DBSession).where(DBSession.id == session_id)
                )
                session = result.scalar_one_or_none()
                if not session:
                    return f"Error: Session '{session_id}' not found."

                if session.request_source != "consultation":
                    return f"Error: Session '{session_id}' is not a consultation."

                session.status = "completed"
                await db.commit()
                return f"Consultation session {session_id} closed."
        except Exception as e:
            logger.exception("cancel_consultation failed")
            return f"Error cancelling consultation: {e}"

    # -----------------------------------------------------------------------
    # Task orchestration tool
    # -----------------------------------------------------------------------

    async def manage_tasks(
        self,
        action: str,
        task_id: str | None = None,
        title: str | None = None,
        description: str | None = None,
        priority: int = 2,
        task_type: str = "task",
        labels: str | None = None,
    ) -> str:
        """Quick task operations via st CLI.

        Args:
            action: list_ready, get_context, create, or dispatch
            task_id: For get_context and dispatch
            title: For create
            description: For create
            priority: For create (0-4, default 2)
            task_type: For create (default: task)
            labels: Comma-separated labels for create

        Returns:
            CLI output
        """
        if action == "list_ready":
            return await self.bash("st ready")

        if action == "get_context":
            if not task_id:
                return "Error: task_id required for get_context"
            return await self.bash(f"st context {task_id}")

        if action == "create":
            if not title:
                return "Error: title required for create"
            cmd = f"st create '{title}' -t {task_type} -p {priority}"
            if description:
                cmd += f" -d '{description}'"
            if labels:
                cmd += f" -l '{labels}'"
            logger.info("manage_tasks create: %s", cmd)
            return await self.bash(cmd)

        if action == "dispatch":
            if not task_id:
                return "Error: task_id required for dispatch"
            return await self.bash(f"st autocode {task_id}")

        return f"Error: Unknown action '{action}'. Use list_ready/get_context/create/dispatch."
