"""First-turn context of a Pi session, read passively from its own session file.

Pi writes a `system` message with named `sections` (the prompt it built) and `toolsAdded` (the tool schemas), then the
user's brief, then the first assistant message with the provider's own `usage`. Agent Hub's delivery is appended to the
system prompt after those sections, so it never shows in them except as an `addendum` section on some launches. Its size
therefore comes from the bound delivery; the sections and tool schemas give the character weights for the harness split.

Pi's session files carry no harness version, so the version is `pi --version` read when the session is first sighted.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app.utils.safe_subprocess import run_process

from . import first_turn

logger = logging.getLogger(__name__)

PI_CORE_SECTIONS = ("preamble", "rules", "docs", "cwd", "project_context")
PI_LISTING_SECTION = "skills"
PI_DELIVERY_SECTION = "addendum"
PI_BIND_WINDOW = timedelta(seconds=20)  # a delivery is built seconds before the session's first call
UNEXPLAINED_MAX_TOKENS = 1500  # residual above this with no bound delivery means a delivery we could not find
VERSION_TIMEOUT_S = 15
VERSION_BASIS_LIVE = "first_sighting"  # `pi --version` run when the session was first captured
VERSION_BASIS_BACKFILL = "installed_at_backfill"  # the session predates its capture: the version installed then


def _section_chars(value: Any) -> int:
    return len(value) if isinstance(value, str) else len(json.dumps(value, separators=(",", ":")))


def read_pi_head(path: Path) -> dict[str, Any] | None:
    """Raw first turn of a Pi session file, or None before its first model reply."""
    raw: dict[str, Any] = {
        "harness": "pi", "sid": None, "cwd": None, "started": None, "model": None, "core_chars": 0, "listing_chars": 0,
        "delivery_chars": 0, "tools_chars": 0, "brief_chars": None, "sections": {},
    }
    for rec in first_turn._iter_head(path):
        kind = rec.get("type")
        if kind == "session":
            raw["sid"] = str(rec["id"]) if rec.get("id") else None
            raw["cwd"] = rec.get("cwd")
            raw["started"] = first_turn._parse_ts(rec.get("timestamp"))
        elif kind == "model_change" and raw["model"] is None:
            raw["model"] = rec.get("modelId")
        elif kind == "message":
            msg = rec.get("message")
            if not isinstance(msg, dict):
                continue
            role = msg.get("role")
            if role == "system" and not raw["sections"]:
                sections = msg.get("sections") if isinstance(msg.get("sections"), dict) else {}
                raw["sections"] = {k: _section_chars(v) for k, v in sections.items()}
                for name, chars in raw["sections"].items():
                    if name == PI_LISTING_SECTION:
                        raw["listing_chars"] += chars
                    elif name == PI_DELIVERY_SECTION:
                        raw["delivery_chars"] += chars
                    else:
                        raw["core_chars"] += chars
                if msg.get("toolsAdded"):
                    raw["tools_chars"] = _section_chars(msg["toolsAdded"])
            elif role == "user" and raw["brief_chars"] is None:
                raw["brief_chars"] = first_turn._text_chars(msg.get("content"))
            elif role == "assistant":
                usage = msg.get("usage")
                ts = first_turn._parse_ts(rec.get("timestamp"))
                if not isinstance(usage, dict) or ts is None:
                    continue
                total = sum(int(usage.get(k) or 0) for k in ("input", "cacheRead", "cacheWrite"))
                if total <= 0:
                    continue
                if not raw["sid"]:
                    return None
                raw.update(
                    total=total, first_at=ts, brief_chars=raw["brief_chars"] or 0,
                    model=raw["model"] or msg.get("model"), started=raw["started"] or ts,
                )
                return raw
    return None


def launch_mode(path: Path, cwd: str | None) -> str:
    return first_turn.launch_mode_for(path, cwd, None)


def compute_parts(raw: dict[str, Any], *, delivery: dict[str, Any] | None, launch: str) -> dict[str, Any]:
    """Stored parts for one Pi first turn. `delivery` is the bound delivery row (est_tokens, blocks) or None.

    ours: the bound delivery; else the `addendum` section when Pi carries the delivery inline; else 0 (exact) for a
    blank-slate launch or when the sections and tool schemas already explain the whole first turn; else unknown.
    """
    total = int(raw["total"])
    brief = first_turn.est_tokens(int(raw.get("brief_chars") or 0))
    weights = {"harness_core": raw["core_chars"], "harness_tools": raw["tools_chars"], "our_listings": raw["listing_chars"]}
    ours: int | None
    if delivery is not None:
        ours, method = int(delivery["est_tokens"]), "estimate"
    elif raw["delivery_chars"]:
        ours, method = first_turn.est_tokens(raw["delivery_chars"]), "estimate"
    elif launch == "blank" or total - brief - first_turn.est_tokens(sum(weights.values())) <= UNEXPLAINED_MAX_TOKENS:
        ours, method = 0, "exact"
    else:
        ours, method = None, "unknown"
    parts: dict[str, Any] = {
        "total": first_turn._part(total, "exact"), "brief": first_turn._part(brief, "estimate"), "ours": first_turn._part(ours, method),
    }
    if ours is None:
        parts["harness"] = first_turn._part(None, "derived")
        for name in first_turn.HARNESS_PART_NAMES:
            parts[name] = first_turn._part(None, "ratio")
    else:
        harness = max(total - ours - brief, 0)
        parts["harness"] = first_turn._part(harness, "derived")
        weight_sum = sum(weights.values())
        if weight_sum > 0:
            shares = {k: harness * v // weight_sum for k, v in weights.items()}
            shares[max(weights, key=lambda k: weights[k])] += harness - sum(shares.values())
            for name in first_turn.HARNESS_PART_NAMES:
                parts[name] = first_turn._part(shares[name], "ratio")
        else:
            for name in first_turn.HARNESS_PART_NAMES:
                parts[name] = first_turn._part(None, "ratio")
    if delivery is not None and ours:
        for name, value in first_turn.split_scope_tokens(delivery.get("blocks") or [], ours).items():
            parts[name] = first_turn._part(value, "estimate")
    else:
        for name in ("ah_global", "ah_role", "ah_project"):
            parts[name] = first_turn._part(0 if ours == 0 else None, "exact")
    parts["chars"] = {
        "brief": int(raw.get("brief_chars") or 0), "ah": raw["delivery_chars"], **weights,
        **{f"section_{k}": v for k, v in raw["sections"].items()},
    }
    return parts


def installed_version() -> str | None:
    """`pi --version`, or None when Pi is not installed for this user (version then shows unknown, never a guess)."""
    exe = shutil.which("pi") or str(Path.home() / ".local" / "bin" / "pi")
    try:
        out = run_process([exe, "--version"], capture_output=True, text=True, timeout=VERSION_TIMEOUT_S, check=False)
    except (OSError, subprocess.SubprocessError):
        logger.info("pi --version unavailable")
        return None
    text = (out.stdout or "").strip().splitlines()
    return text[0].strip()[:40] if out.returncode == 0 and text else None


def version_basis(started: datetime, now: datetime, *, live_within: timedelta = timedelta(hours=1)) -> str:
    """What `pi --version` read at `now` means for a session that started at `started`.

    A recent session is sighted live, so the version is the one it ran. An older one is only being captured now
    (backfill, or a collector that was down), so the installed version is the first-sighting version, not proof.
    """
    return VERSION_BASIS_LIVE if now - started <= live_within else VERSION_BASIS_BACKFILL
