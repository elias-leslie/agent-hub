"""First-turn context of a harness session, read passively from its own transcript head.

A first turn is the first model request of a Claude Code or Codex session: everything the harness, our config and
Agent Hub put in front of the model before the user's brief. Its total is exact (the provider's own count). The split
is derived: ours comes from the bound Agent Hub delivery, the brief from the first user text, and the harness remainder
is divided across its parts by character weight (method "ratio"). Nothing here patches or probes a harness.

`read_claude_head` / `read_codex_head` read only the transcript's head, so the same code serves the live collector and
the 30-day backfill. `compute_parts` turns the raw head plus the bound delivery into the stored parts.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

HEAD_MAX_LINES = 600
HEAD_MAX_BYTES = 6_000_000
CHARS_PER_TOKEN = 4  # Agent Hub's own estimate (services/memory/budget.py): ours and the brief use it too

HARNESS_PART_NAMES = ("harness_core", "harness_tools", "our_listings")
BLANK_SLATE_MARKER = "blank-slate"

# Claude Code records the whole request shape once per session; `instructions` carries our delivered CLAUDE.md.
_CLAUDE_LISTING_ATTACHMENTS = ("skill_listing", "agent_listing_delta", "mcp_instructions_delta", "deferred_tools_delta")


def est_tokens(chars: int) -> int:
    return chars // CHARS_PER_TOKEN


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed


def _text_chars(content: Any) -> int:
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        return sum(len(b.get("text") or "") for b in content if isinstance(b, dict) and b.get("type") in (None, "text", "input_text"))
    return 0


def _listing_chars(att: dict[str, Any]) -> int:
    kind = att.get("type")
    if kind == "skill_listing":
        return len(att.get("content") or "")
    if kind == "agent_listing_delta":
        return sum(len(x) for x in att.get("addedLines") or [] if isinstance(x, str))
    if kind == "mcp_instructions_delta":
        return sum(len(x) for x in att.get("addedBlocks") or [] if isinstance(x, str))
    if kind == "deferred_tools_delta":
        return sum(len(x) for x in att.get("addedLines") or [] if isinstance(x, str))
    return 0


def _iter_head(path: Path):
    """Yield parsed JSON records from the start of a transcript until the caps."""
    read = 0
    with path.open("rb") as fh:
        for n, line in enumerate(fh):
            read += len(line)
            if n >= HEAD_MAX_LINES or read > HEAD_MAX_BYTES:
                return
            if not line.endswith(b"\n") or line.startswith(b'{"type":"api-request-blob"'):
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if isinstance(rec, dict):
                yield rec


def launch_mode_for(path: Path, cwd: str | None, agent_type: str | None) -> str:
    if agent_type is not None:
        return f"subagent:{agent_type or 'unknown'}"
    if BLANK_SLATE_MARKER in str(path) or BLANK_SLATE_MARKER in (cwd or ""):
        return "blank"
    return "project"


def claude_identity(path: Path) -> tuple[str, str]:
    """(session id, agent id) of a Claude Code transcript: <session>.jsonl or <session>/subagents/agent-<id>.jsonl."""
    if path.parent.name == "subagents":
        return path.parent.parent.name, path.stem.removeprefix("agent-")
    return path.stem, ""


def claude_agent_type(path: Path) -> str | None:
    """agentType of an in-process sub-agent transcript (None for a main session)."""
    if path.parent.name != "subagents":
        return None
    try:
        meta = json.loads(path.with_suffix(".meta.json").read_text())
    except (OSError, ValueError):
        return ""
    return str(meta.get("agentType") or "") if isinstance(meta, dict) else ""


def read_claude_head(path: Path) -> dict[str, Any] | None:
    """Raw first turn of a Claude Code transcript (main or sub-agent), or None before its first model call."""
    raw: dict[str, Any] = {
        "harness": "claude", "sys_chars": 0, "tools_chars": 0, "listing_chars": 0, "shape": False, "fp": None,
        "inst_files": [], "brief_chars": None, "version": None,
    }
    for rec in _iter_head(path):
        kind = rec.get("type")
        if kind == "api-request-shape" and not raw["shape"]:
            shape = rec.get("shape") or {}
            raw["shape"] = True
            raw["fp"] = rec.get("shapeHash")
            raw["version"] = rec.get("version")
            raw["sys_chars"] = sum(
                len(b.get("text") or "") for b in shape.get("system") or [] if isinstance(b, dict)
            )
            raw["tools_chars"] = len(json.dumps(shape.get("tools") or [], separators=(",", ":")))
        elif kind == "attachment":
            att = rec.get("attachment") or {}
            if att.get("type") in _CLAUDE_LISTING_ATTACHMENTS:
                raw["listing_chars"] += _listing_chars(att)
            elif att.get("type") == "instructions":
                for item in att.get("files") or []:
                    content = item.get("content") if isinstance(item, dict) else None
                    if isinstance(content, str) and content:
                        raw["inst_files"].append({
                            "path": item.get("path"), "chars": len(content),
                            "sha": hashlib.sha256(content.encode()).hexdigest(),
                        })
        elif kind == "user" and raw["brief_chars"] is None and not rec.get("isMeta"):
            content = (rec.get("message") or {}).get("content")
            if isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
                continue
            raw["brief_chars"] = _text_chars(content)
            raw["cwd"] = rec.get("cwd")
        elif kind == "assistant":
            msg = rec.get("message")
            usage = msg.get("usage") if isinstance(msg, dict) else None
            model = msg.get("model") if isinstance(msg, dict) else None
            ts = _parse_ts(rec.get("timestamp"))
            if not isinstance(usage, dict) or not isinstance(model, str) or model.startswith("<") or ts is None:
                continue
            total = sum(int(usage.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
            if total <= 0:
                continue
            raw.update(
                total=total, model=model, first_at=ts, version=rec.get("version") or raw["version"],
                cwd=rec.get("cwd") or raw.get("cwd"), brief_chars=raw["brief_chars"] or 0,
            )
            return raw
    return None


def _codex_message_text(payload: dict[str, Any]) -> str:
    return "".join(c.get("text") or "" for c in payload.get("content") or [] if isinstance(c, dict))


def read_codex_head(path: Path) -> dict[str, Any] | None:
    """Raw first turn of a Codex rollout, or None before its first token count. Developer texts are kept for binding."""
    raw: dict[str, Any] = {
        "harness": "codex", "tools_chars": 0, "base_chars": 0, "skills_chars": 0, "env_chars": 0, "brief_chars": None,
        "dev_texts": [], "version": None, "model": None, "cwd": None,
    }
    tools_text = base_text = ""
    seen_meta = False
    for rec in _iter_head(path):
        kind = rec.get("type")
        payload = rec.get("payload") if isinstance(rec.get("payload"), dict) else {}
        if kind == "session_meta" and not seen_meta:
            seen_meta = True
            raw["version"] = payload.get("cli_version")
            raw["cwd"] = payload.get("cwd")
            raw["originator"] = payload.get("originator")
            own = payload.get("id")
            root = payload.get("session_id") or payload.get("parent_thread_id") or own
            raw["sid"] = str(root) if root else None
            raw["aid"] = str(own) if own and own != root else ""
        elif kind == "turn_context" and raw["model"] is None:
            raw["model"] = payload.get("model")
        elif kind == "response_item":
            ptype = payload.get("type")
            if ptype == "additional_tools":
                tools_text = json.dumps(payload.get("tools"), separators=(",", ":"))
                raw["tools_chars"] += len(tools_text)
            elif ptype == "message":
                text = _codex_message_text(payload)
                role = payload.get("role")
                if role == "developer":
                    if text.startswith("You are Codex"):
                        base_text = text
                        raw["base_chars"] += len(text)
                    elif text.startswith("<skills_instructions>"):
                        raw["skills_chars"] += len(text)
                    else:
                        raw["dev_texts"].append(text)
                elif role == "user":
                    if text.startswith(("<environment_context", "# AGENTS.md", "<user_instructions")):
                        raw["env_chars"] += len(text)
                    elif raw["brief_chars"] is None:
                        raw["brief_chars"] = len(text)
        elif kind == "event_msg" and payload.get("type") == "token_count" and payload.get("info"):
            last = (payload["info"] or {}).get("last_token_usage") or {}
            total = int(last.get("input_tokens") or 0)
            ts = _parse_ts(rec.get("timestamp"))
            if total <= 0 or ts is None:
                continue
            raw.update(total=total, first_at=ts, brief_chars=raw["brief_chars"] or 0)
            raw["fp"] = hashlib.sha256((tools_text + "\0" + base_text).encode()).hexdigest()[:16]
            return raw
    return None


def split_scope_tokens(blocks: list[dict[str, Any]], total: int) -> dict[str, int]:
    """Delivered tokens by scope bucket (global, role, project), scaled so the buckets add up to the delivery total."""
    raw = {"ah_global": 0, "ah_role": 0, "ah_project": 0}
    for block in blocks:
        scope = block.get("scope")
        bucket = "ah_project" if scope == "project" else "ah_global" if scope in (None, "global") else "ah_role"
        raw[bucket] += int(block.get("tokens") or 0)
    weight = sum(raw.values())
    if weight <= 0 or total <= 0:
        return raw
    scaled = {k: v * total // weight for k, v in raw.items()}
    scaled[max(raw, key=lambda k: raw[k])] += total - sum(scaled.values())
    return scaled


def _part(tokens: int | None, method: str) -> dict[str, Any]:
    return {"tokens": tokens, "method": method if tokens is not None else "unknown"}


def compute_parts(
    raw: dict[str, Any], *, delivery: dict[str, Any] | None, launch_mode: str, ah_chars_in_text: int | None = None
) -> dict[str, Any]:
    """Stored parts for one first turn. `delivery` is the bound delivery row (est_tokens, blocks) or None.

    ours is 0 (exact) for a blank-slate launch, which gets no delivery, and for a Claude session whose transcript
    shows no delivered instructions; it is unknown when a project launch could not be bound.
    """
    total = int(raw["total"])
    brief = est_tokens(int(raw.get("brief_chars") or 0))
    chars: dict[str, int] = {"brief": int(raw.get("brief_chars") or 0)}
    if raw["harness"] == "claude":
        inst_chars = sum(int(f["chars"]) for f in raw.get("inst_files") or [])
        weights = {"harness_core": raw["sys_chars"], "harness_tools": raw["tools_chars"], "our_listings": raw["listing_chars"]}
        chars.update(inst=inst_chars, **weights)
        if delivery is not None:
            ours: int | None = int(delivery["est_tokens"])
            ours_method = "estimate"
        elif inst_chars:
            ours, ours_method = est_tokens(inst_chars), "estimate"
        else:
            ours, ours_method = 0, "exact"
    else:
        other_chars = sum(len(t) for t in raw.get("dev_texts") or [])
        ah_chars = ah_chars_in_text or 0
        weights = {
            "harness_core": raw["base_chars"] + raw["env_chars"] + max(other_chars - ah_chars, 0),
            "harness_tools": raw["tools_chars"], "our_listings": raw["skills_chars"],
        }
        chars.update(weights, ah=ah_chars)
        if delivery is not None:
            ours, ours_method = int(delivery["est_tokens"]), "estimate"
        elif launch_mode == "blank":
            ours, ours_method = 0, "exact"
        else:
            ours, ours_method = None, "unknown"
    parts: dict[str, Any] = {"total": _part(total, "exact"), "brief": _part(brief, "estimate"), "ours": _part(ours, ours_method)}
    if ours is None:
        parts["harness"] = _part(None, "derived")
        for name in HARNESS_PART_NAMES:
            parts[name] = _part(None, "ratio")
    else:
        harness = max(total - ours - brief, 0)
        parts["harness"] = _part(harness, "derived")
        weight_sum = sum(weights.values())
        if weight_sum > 0:
            shares = {k: harness * v // weight_sum for k, v in weights.items()}
            shares[max(weights, key=lambda k: weights[k])] += harness - sum(shares.values())
            for name in HARNESS_PART_NAMES:
                parts[name] = _part(shares[name], "ratio")
        else:
            for name in HARNESS_PART_NAMES:
                parts[name] = _part(None, "ratio")
    if delivery is not None and ours:
        for name, value in split_scope_tokens(delivery.get("blocks") or [], ours).items():
            parts[name] = _part(value, "estimate")
    else:
        for name in ("ah_global", "ah_role", "ah_project"):
            parts[name] = _part(0 if ours == 0 else None, "exact")
    parts["chars"] = chars
    return parts
