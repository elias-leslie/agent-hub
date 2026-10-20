"""Inspect the saved launch artifact; this does not establish model receipt."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Annotated, Any

import typer
from st_sdk.context import OutputContext
from st_sdk.output import output_error, output_json
from st_sdk.usage import usage

from .context_budget import context_warnings

_CONTRACT_ENV = "AGENT_HUB_CONTEXT_PREINJECTED_CONTRACT"


def _saved_contract() -> dict[str, Any]:
    path = os.getenv(_CONTRACT_ENV)
    if not path:
        raise ValueError(f"{_CONTRACT_ENV} is not set")
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("saved contract must be an object")
    rendered = data.get("rendered")
    if not isinstance(rendered, str) or not rendered.strip():
        raise ValueError("saved rendered text is missing or empty")
    if data.get("payload_hash_algorithm", "sha256") != "sha256":
        raise ValueError("saved hash algorithm must be sha256")
    if data.get("payload_hash") != hashlib.sha256(rendered.encode("utf-8")).hexdigest():
        raise ValueError("saved SHA-256 does not match rendered UTF-8 text")
    if data.get("status") not in ("ok", "failed"):
        raise ValueError("saved status must be ok or failed")
    blocks = data.get("blocks")
    if not isinstance(blocks, list) or not all(isinstance(block, dict) for block in blocks):
        raise ValueError("saved blocks must be a list of objects")
    for block in blocks:
        if not all(isinstance(block.get(key), str) for key in ("block_id", "kind", "title")):
            raise ValueError("saved block identifiers, kinds and titles must be strings")
        if type(block.get("estimated_tokens")) is not int or block["estimated_tokens"] < 0:
            raise ValueError("saved block estimated_tokens must be a nonnegative integer")
    if type(data.get("estimated_tokens")) is not int or data["estimated_tokens"] < 0:
        raise ValueError("saved estimated_tokens must be a nonnegative integer")
    if not isinstance(data.get("metadata", {}), dict):
        raise ValueError("saved metadata must be an object")
    return data


@usage(surface="st.mandates", cmd="st mandates", when="inspect saved startup context (blocks, token estimates and validated SHA-256)",
       task_types=("agent-admin",), on_demand="agent context")
def mandates(
    ctx: typer.Context,
    full: Annotated[bool, typer.Option("--full", help="Print the exact saved rendered context text")] = False,
) -> None:
    """Inspect the saved startup context artifact named by the launcher.

    \b
    Examples:
      st mandates
      st mandates --full
      st --no-compact mandates
    """
    out = ctx.obj if isinstance(ctx.obj, OutputContext) else OutputContext()
    try:
        delivery = _saved_contract()
    except (OSError, ValueError, UnicodeError) as exc:
        output_error(f"Saved startup artifact unavailable or invalid: {exc}. This does not establish what instructions the model received.")
        raise typer.Exit(1) from exc
    blocks = [
        {key: block.get(key) for key in ("block_id", "kind", "title", "estimated_tokens")}
        for block in delivery["blocks"]
    ]
    scope = str(delivery.get("metadata", {}).get("project_id") or "global")
    warnings = context_warnings(delivery["blocks"], delivery["estimated_tokens"], scope=scope)
    rendered = delivery["rendered"]
    if full:
        print(rendered, end="")
        return
    if not out.is_compact:
        output_json({
            "items": blocks, "count": len(blocks), "status": delivery["status"], "scope": scope,
            "source": "saved", "estimated_tokens": delivery["estimated_tokens"],
            "payload_hash": delivery["payload_hash"], "rendered_bytes": len(rendered.encode("utf-8")),
            "warnings": warnings,
        })
        return
    for block in blocks:
        print(f"{block['block_id']} {block['kind']} tokens={block['estimated_tokens']} {block['title']}")
    print(
        f"CONTEXT:{delivery['status']}|source=saved|scope={scope}|blocks={len(blocks)}|tokens={delivery['estimated_tokens']}"
        f"|bytes={len(rendered.encode('utf-8'))}|hash={delivery['payload_hash'][:12]}"
    )
    for warning in warnings:
        print(warning)
