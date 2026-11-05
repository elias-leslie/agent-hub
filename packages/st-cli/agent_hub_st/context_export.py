"""Bounded context-export command owned by Agent Hub."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any

import typer
from st_sdk.output import output_json
from st_sdk.usage import usage


class ContextCollection(StrEnum):
    memories = "memories"
    memory_settings = "memory_settings"
    prompts = "prompts"
    agents = "agents"
    budgets = "budgets"
    project_rows = "project_rows"
    project_hash = "project_hash"


@usage(
    surface="st.agents.context-export",
    cmd="st agents context-export COLLECTION --offset N --limit N [--agent-role ROLE]",
    when="read one bounded context import page as JSON; repeat --agent-role for the agents collection",
    on_demand="agent administration",
    tier="reference",
)
def context_export(
    collection: Annotated[ContextCollection, typer.Argument(help="Context collection.")],
    offset: Annotated[int, typer.Option("--offset", min=0)] = 0,
    limit: Annotated[int, typer.Option("--limit", min=1, max=1000)] = 1000,
    agent_role: Annotated[list[str] | None, typer.Option("--agent-role", help="Agent role slug; repeat for each role.")] = None,
) -> None:
    """Print one context export page as JSON."""
    from .memory_api import agent_hub_request

    params: dict[str, Any] = {"offset": offset, "limit": limit}
    if agent_role:
        params["agent_role"] = agent_role
    output_json(agent_hub_request(
        "GET", f"/api/context-export/{collection.value}", params=params,
        internal=True, tool_name="st agents context-export",
    ))
