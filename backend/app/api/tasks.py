"""Read-only task search helpers for chat context selection."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter(prefix="/tasks", tags=["tasks"])


class TaskSearchItem(BaseModel):
    id: str
    project_id: str
    title: str
    description: str | None = None
    status: str
    priority: int | None = None
    task_type: str | None = None


class TaskSearchResponse(BaseModel):
    tasks: list[TaskSearchItem]
    total: int


def _matches_query(task: dict[str, Any], query: str) -> bool:
    if not query:
        return True
    haystack = " ".join(
        str(task.get(key) or "")
        for key in ("id", "project_id", "title", "description", "status", "task_type")
    ).lower()
    return query.lower() in haystack


async def _run_st_task_list(project_id: str, status: str | None, limit: int) -> dict[str, Any]:
    command = ["st", "-P", project_id, "list", "--json", "--limit", str(limit)]
    if status:
        command.extend(["--status", status])

    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=8)
    except TimeoutError as exc:
        process.kill()
        await process.communicate()
        raise HTTPException(status_code=504, detail="Task search timed out") from exc

    if process.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace").strip() or "Task search failed"
        raise HTTPException(status_code=502, detail=detail)

    try:
        payload = json.loads(stdout.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail="Task search returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="Task search returned invalid payload")
    return payload


@router.get("/search", response_model=TaskSearchResponse)
async def search_tasks(
    project_id: str = Query(..., min_length=1),
    q: str = Query(default="", max_length=200),
    status: str | None = Query(default="pending", max_length=40),
    limit: int = Query(default=25, ge=1, le=100),
) -> TaskSearchResponse:
    """Search task titles/descriptions for one project.

    The durable task store is owned by ST, not Agent Hub ORM models. This route
    intentionally stays read-only and delegates to the canonical ST list surface.
    """

    payload = await _run_st_task_list(project_id, status, limit)
    raw_tasks = payload.get("tasks", [])
    if not isinstance(raw_tasks, list):
        raise HTTPException(status_code=502, detail="Task search payload missing tasks")

    tasks = [
        TaskSearchItem(
            id=str(task.get("id") or ""),
            project_id=str(task.get("project_id") or project_id),
            title=str(task.get("title") or task.get("id") or ""),
            description=task.get("description") if isinstance(task.get("description"), str) else None,
            status=str(task.get("status") or ""),
            priority=task.get("priority") if isinstance(task.get("priority"), int) else None,
            task_type=task.get("task_type") if isinstance(task.get("task_type"), str) else None,
        )
        for task in raw_tasks
        if isinstance(task, dict) and task.get("id") and _matches_query(task, q.strip())
    ]

    return TaskSearchResponse(tasks=tasks[:limit], total=len(tasks))
