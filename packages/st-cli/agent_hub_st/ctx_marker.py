"""One line per marker for ``st ctx markers``: what changed, not the kind twice."""

from __future__ import annotations

from typing import Any

from .ctx_format import UNKNOWN, fp, obj, short, tok, when


def _cell(marker: dict[str, Any]) -> str:
    """The sessions a config marker is about: their role, or how they were launched when they have none."""
    return str(marker.get("work_role") or marker.get("launch_mode") or UNKNOWN)


def marker_line(marker: dict[str, Any]) -> str:
    kind, detail = marker.get("kind"), obj(marker.get("detail"))
    who = detail.get("writer_session") or detail.get("writer_kind")
    by = f" by {short(who, 16)}" if who else ""
    if kind == "config":
        return (f"{when(marker.get('at'))} config: {marker.get('harness') or UNKNOWN} {_cell(marker)} sessions on {detail.get('model') or UNKNOWN}"
                f" v{detail.get('version') or UNKNOWN} sent a new request shape, {fp(detail.get('from_fp'))} -> {fp(marker.get('ref'))}")
    if kind == "harness_version":
        return f"{when(marker.get('at'))} new version: {short(marker.get('label'), 40)} first seen"
    if kind == "knob":
        return f"{when(marker.get('at'))} our config file {short(marker.get('label'), 30)} changed: {short(detail.get('subject'), 50)}"
    if kind in ("memory", "prompt"):
        version = f" (revision {detail['version']})" if detail.get("version") is not None else ""
        size = f", {tok(detail.get('tokens'))} tokens" if detail.get("tokens") is not None else ""
        return f"{when(marker.get('at'))} {kind} {detail.get('action') or 'changed'}: {short(marker.get('label'), 40)}{version}{size}{by}"
    if kind == "placement":
        return f"{when(marker.get('at'))} placement change: {short(marker.get('label'), 40)}{by}"
    return f"{when(marker.get('at'))} {kind} {short(marker.get('label'), 40)}{by}"
