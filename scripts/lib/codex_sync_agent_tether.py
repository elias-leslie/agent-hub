"""Open Codex rollouts of agent users, for codex-session-sync: what the service user can read of another user's session.

/proc/<pid>/environ and fd of another user's processes are not readable, so the live-process view in
codex_sync_transcripts cannot see them. This maps each agent rollout to its Aico/Tether window with what is readable:
the rollout header (cwd, thread ids) and the agent Tether's session list over its control socket (the service user's
group may connect). A window with one candidate rollout gives that rollout an owner; several windows in one project
cannot be told apart, so their rollouts are marked ambiguous (the sync records the conflict) instead of guessed.
"""

from __future__ import annotations

import http.client
import json
import os
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from codex_sync_transcripts import (
    AicoProcessOwner,
    TRANSCRIPTS_ROOT,
    OpenTranscriptSnapshot,
    _native_identity,
    _safe_identifier,
    transcript_roots,
)

# Same default as SummitFlow's TETHER_AGENT_SOCKET_DEFAULT; AGENT_HUB_TETHER_SOCKETS (os.pathsep-separated, empty: none).
DEFAULT_SOCKETS = ("/run/tether/agent/default/control.sock",)
TETHER_TIMEOUT_S = 3.0
BODY_LIMIT = 1024 * 1024
HEADER_LIMIT = 1024 * 1024
# A child (subagent) rollout counts as open while it was written this recently and its root is open; when Tether
# cannot be asked, rollouts written this recently count as open so a live session is not closed by the inactive pass.
ACTIVE_S = float(os.environ.get("AGENT_HUB_CODEX_ACTIVE_S") or 600)


@dataclass(frozen=True)
class Rollout:
    path: Path
    session_id: str
    parent_id: str | None
    cwd: Path
    mtime: float


def tether_sockets() -> list[Path]:
    configured = os.environ.get("AGENT_HUB_TETHER_SOCKETS")
    raw = DEFAULT_SOCKETS if configured is None else tuple(p for p in configured.split(os.pathsep) if p.strip())
    return [Path(p) for p in raw]


def list_codex_sessions(sock_path: Path) -> list[dict] | None:
    """Codex sessions of one Tether instance (GET /v1/sessions?tool=codex); None when it cannot be asked."""
    class Conn(http.client.HTTPConnection):
        def connect(self) -> None:
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.settimeout(TETHER_TIMEOUT_S)
            self.sock.connect(str(sock_path))

    conn = Conn("tether", timeout=TETHER_TIMEOUT_S)
    try:
        conn.request("GET", "/v1/sessions?tool=codex", headers={"Connection": "close"})
        resp = conn.getresponse()
        raw = resp.read(BODY_LIMIT + 1)
        if resp.status != 200 or len(raw) > BODY_LIMIT:
            return None
        items = json.loads(raw).get("items")
    except (OSError, ValueError, AttributeError, http.client.HTTPException):
        return None
    finally:
        conn.close()
    return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else None


def _rollout(path: Path, since: float) -> Rollout | None:
    """The rollout's header identity, for a file written at or after `since`."""
    try:
        mtime = path.stat().st_mtime
        if mtime < since:
            return None
        with path.open("rb") as fh:
            first = fh.readline(HEADER_LIMIT)
        obj = json.loads(first)
    except (OSError, ValueError):
        return None
    payload = obj.get("payload") if isinstance(obj, dict) and obj.get("type") == "session_meta" else None
    if not isinstance(payload, dict):
        return None
    ident = _native_identity(payload)
    if ident["identity_error"] or not ident["session_id"] or not ident["cwd"]:
        return None
    return Rollout(path.resolve(strict=False), str(ident["session_id"]), ident["parent_session_id"] or None,
                   Path(str(ident["cwd"])), mtime)


def _agent_rollouts(roots: list[Path], since: float) -> list[Rollout]:
    out: list[Rollout] = []
    for root in roots:
        try:
            files = list(root.rglob("*.jsonl"))
        except OSError:
            continue
        out += [r for p in files if (r := _rollout(p, since))]
    return out


def _owner(item: dict) -> AicoProcessOwner | None:
    wid, oid = _safe_identifier(item.get("id")), _safe_identifier(item.get("ownershipId"))
    project = item.get("projectId")
    if not wid or not oid or not (project is None or isinstance(project, str)):
        return None
    return AicoProcessOwner(harness="codex", aico_session_id=oid, aico_widget_id=wid, aico_project_id=project or "")


def _root_of(r: Rollout, by_id: dict[str, Rollout]) -> Rollout:
    for _ in range(16):
        parent = by_id.get(r.parent_id or "")
        if parent is None:
            return r
        r = parent
    return r


def discover_agent_transcripts(
    *,
    roots: list[Path] | None = None,
    sockets: list[Path] | None = None,
    list_fn: Callable[[Path], list[dict] | None] = list_codex_sessions,
    now: float | None = None,
    log_fn: Callable[[str], None] | None = None,
) -> OpenTranscriptSnapshot:
    """Open agent-user rollouts and their Aico owners. Roots are the other users' rollout dirs (the service user's
    own are the /proc view's). No reachable agent Tether: nothing is claimed open, except what was written within ACTIVE_S
    when a Tether socket exists but does not answer."""
    now = time.time() if now is None else now
    own = TRANSCRIPTS_ROOT.expanduser().resolve(strict=False)
    roots = [r for r in transcript_roots() if r.expanduser().resolve(strict=False) != own] if roots is None else roots
    sockets = [s for s in (tether_sockets() if sockets is None else sockets) if _exists(s)]
    if not roots or not sockets:
        return OpenTranscriptSnapshot.empty()
    answers = [list_fn(s) for s in sockets]
    widgets = [i for got in answers if got for i in got if i.get("tool") == "codex" and i.get("status") == "running"
               and i.get("available") is not False and isinstance(i.get("createdAt"), int | float)]
    failed = any(got is None for got in answers)
    if failed and log_fn:
        log_fn("[WARN] agent Tether did not answer; agent Codex rollouts written recently count as open")
    if not widgets and not failed:
        return OpenTranscriptSnapshot.empty()
    since = min((w["createdAt"] / 1000.0 for w in widgets), default=now - ACTIVE_S)
    if failed:
        since = min(since, now - ACTIVE_S)
    rollouts = _agent_rollouts(roots, since)
    by_id = {r.session_id: r for r in rollouts}
    roots_only = sorted((r for r in rollouts if r.parent_id is None), key=lambda r: -r.mtime)
    paths: set[Path] = set()
    owners: dict[Path, AicoProcessOwner] = {}
    ambiguous: set[Path] = set()
    by_cwd: dict[Path, list[dict]] = {}
    for w in widgets:
        if isinstance(w.get("projectRoot"), str):
            by_cwd.setdefault(Path(w["projectRoot"]), []).append(w)
    claimed: dict[Path, Rollout] = {}  # open root rollout path -> itself
    for cwd, ws in by_cwd.items():
        mine = [r for r in roots_only if r.cwd == cwd and r.mtime >= min(w["createdAt"] for w in ws) / 1000.0]
        current = mine[: len(ws)]  # each window holds its newest rollout; older ones were replaced in it
        for r in current:
            paths.add(r.path)
            claimed[r.path] = r
            if len(ws) == 1 and (owner := _owner(ws[0])):
                owners[r.path] = owner
            else:
                ambiguous.add(r.path)
    if failed:
        paths |= {r.path for r in rollouts if now - r.mtime <= ACTIVE_S}
    for r in rollouts:  # children of an open root: open while recently written, owned like the root
        root = _root_of(r, by_id)
        if root is r or root.path not in claimed or now - r.mtime > ACTIVE_S:
            continue
        paths.add(r.path)
        if root.path in owners:
            owners[r.path] = owners[root.path]
        elif root.path in ambiguous:
            ambiguous.add(r.path)
    return OpenTranscriptSnapshot(paths=frozenset(paths), owners=owners, ambiguous_paths=frozenset(ambiguous))


def _exists(path: Path) -> bool:
    try:
        return path.is_socket()
    except OSError:
        return False


def merge_snapshots(a: OpenTranscriptSnapshot, b: OpenTranscriptSnapshot) -> OpenTranscriptSnapshot:
    """The /proc view first: a path both know keeps the process view's owner."""
    return OpenTranscriptSnapshot(paths=a.paths | b.paths, owners={**b.owners, **a.owners},
                                  ambiguous_paths=a.ambiguous_paths | (b.ambiguous_paths - set(a.owners)))
