"""`st mandates` — show the canonical startup context Agent Hub injects.

SessionStart hooks and launchers inject one canonical delivery
(`/api/runtime-context/deliver`): DB prompt blocks, the computed tool-capability
block and the project index. This command requests the same delivery for the
current surface and cwd and, when the launcher exported a preinjected contract
(`AGENT_HUB_CONTEXT_PREINJECTED_CONTRACT`), replays that contract's request
inputs and reports whether the session's injected bytes still match.

Bare payload per docs/contracts/01-output-conventions.md: JSON modes emit
`{items, count, ...}` where items are block summaries; compact prints one line
per block plus a summary line. `--full` prints the rendered context instead.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated, Any

import typer
from st_sdk.context import OutputContext
from st_sdk.output import output_json
from st_sdk.usage import usage

from .memory_api import agent_hub_request

_DELIVER_PATH = "/api/runtime-context/deliver"
_CONTRACT_ENV = "AGENT_HUB_CONTEXT_PREINJECTED_CONTRACT"
# Contract metadata echoes the request; query_hash is derived server-side.
_NOT_REPLAYED = frozenset({"query_hash"})
_SURFACE_ENV = (("CLAUDECODE", "claude_code"), ("CODEX_THREAD_ID", "codex"))


def _detect_surface() -> str:
    for env, surface in _SURFACE_ENV:
        if os.getenv(env):
            return surface
    return "agent_hub"


def _injected_contract() -> dict[str, Any] | None:
    path = os.getenv(_CONTRACT_ENV)
    if not path:
        return None
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _request(surface: str | None, injected: dict[str, Any] | None) -> dict[str, Any]:
    meta = (injected or {}).get("metadata") or {}
    body = {key: value for key, value in meta.items() if key not in _NOT_REPLAYED and value is not None}
    if surface:
        body["consumer_surface"] = surface
    body.setdefault("consumer_surface", _detect_surface())
    body.setdefault("cwd", os.getcwd())
    body.setdefault("capabilities", ["bash"])
    return body


def _blocks(delivery: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {key: block.get(key) for key in ("block_id", "kind", "title", "estimated_tokens")}
        for block in delivery.get("blocks") or []
        if isinstance(block, dict)
    ]


@usage(surface="st.mandates", cmd="st mandates", when="verify the startup context Agent Hub injects (blocks, tokens, injected-hash match)",
       task_types=("agent-admin",), on_demand="agent context")
def mandates(
    ctx: typer.Context,
    surface: Annotated[str | None, typer.Option("--surface", help="Consumer surface (default: injected contract or detected harness)")] = None,
    full: Annotated[bool, typer.Option("--full", help="Print the rendered context text")] = False,
) -> None:
    """Show the canonical startup context injected into new agent sessions.

    \b
    Examples:
      st mandates
      st mandates --full
      st mandates --surface codex
      st --no-compact mandates
    """
    out = ctx.obj if isinstance(ctx.obj, OutputContext) else OutputContext()
    injected = _injected_contract()
    delivery = agent_hub_request(
        "POST", _DELIVER_PATH, json=_request(surface, injected), tool_name="st mandates", internal=True, retries=2,
    )
    blocks = _blocks(delivery)
    injected_hash = (injected or {}).get("payload_hash")
    match = None if not injected_hash or surface else injected_hash == delivery.get("payload_hash")
    if full:
        print(delivery.get("rendered") or "", end="")
        return
    if not out.is_compact:
        output_json({
            "items": blocks, "count": len(blocks), "status": delivery.get("status"),
            "estimated_tokens": delivery.get("estimated_tokens"), "payload_hash": delivery.get("payload_hash"),
            "rendered_bytes": len((delivery.get("rendered") or "").encode()),
            "injected_hash": injected_hash, "injected_match": match,
        })
        return
    for block in blocks:
        print(f"{block['block_id']} {block['kind']} tokens={block['estimated_tokens']} {block['title']}")
    injected_state = "none" if match is None else ("match" if match else "differs")
    print(
        f"CONTEXT:{delivery.get('status')}|blocks={len(blocks)}|tokens={delivery.get('estimated_tokens')}"
        f"|bytes={len((delivery.get('rendered') or '').encode())}|hash={str(delivery.get('payload_hash'))[:12]}"
        f"|injected={injected_state}"
    )
