"""`st mandates` — fetch the active mandate union from Agent Hub on demand.

SessionStart hooks inject mandates at launch; this is the on-demand re-fetch
path returning the same set (memory records with injection_tier == "mandate",
rendered for model consumption). Real implementation over Agent Hub's
`/api/memory/progressive-context`, whose mandate block is deterministic
(injected regardless of query), so a stable placeholder query is used.

Bare payload per docs/contracts/01-output-conventions.md: JSON modes emit
`{items, count}`; compact prints the rendered mandate texts back to back (the
form a model consumes). No `{ok, data}` envelope.
"""

from __future__ import annotations

import typer
from st_sdk.usage import usage
from st_sdk.context import OutputContext
from st_sdk.output import output_json

from .memory_api import agent_hub_request

_PROGRESSIVE_CONTEXT_PATH = "/api/memory/progressive-context"


@usage(surface="st.mandates", cmd="st mandates", when="read the active canonical mandate union",
       task_types=("agent-admin",), on_demand="agent context")
def mandates(ctx: typer.Context) -> None:
    """Print the active mandate union (same set SessionStart hooks inject).

    Examples: st mandates | st mandates --human | st mandates --no-compact
    """
    out = ctx.obj if isinstance(ctx.obj, OutputContext) else OutputContext()
    data = agent_hub_request(
        "GET",
        _PROGRESSIVE_CONTEXT_PATH,
        params={"query": "mandates", "consumer_profile": "agent_startup"},
        tool_name="st mandates",
        retries=2,
    )
    block = data.get("mandates") or {}
    items = block.get("items") or []
    if out.is_compact:
        for item in items:
            print(item)
    else:
        output_json({"items": items, "count": len(items)})
