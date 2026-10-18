"""Runtime orchestration for codex-session-sync."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from codex_sync_api import finalize_and_close, ingest_transcript, send_heartbeat, upsert_session
from codex_sync_bindings import (
    ProjectBinding,
    sync_lock,
)
from codex_sync_bindings import (
    load_snapshot as load_project_bindings,
)
from codex_sync_bindings import (
    save_snapshot_locked as save_project_bindings_locked,
)
from codex_sync_git import build_project_context, fetch_registered_project_root
from codex_sync_state import (
    PERMANENT_HTTP_STATUSES,
    entry_is_permanent_error,
    get_checkpoint,
    get_state_entry,
    iter_nonterminal_paths,
    load_state,
    save_state,
    should_heartbeat,
    should_sync,
    update_state_entry,
)
from codex_sync_transcripts import (
    AICO_PERSONAL_PROJECT_ID,
    AicoProcessOwner,
    OpenTranscriptSnapshot,
    discover_open_transcripts,
    external_agent_path,
    has_live_codex_process,
    iter_recent_transcripts,
    read_transcript_info,
)

LogFn = Callable[[str], None]


class TranscriptInfoLike(Protocol):
    session_id: str
    path: Path
    cwd: Path
    model: str
    mtime: float
    size: int
    parent_session_id: str | None
    agent_nickname: str | None
    agent_path: str | None
    is_open: bool
    process_owner: AicoProcessOwner | None
    ownership_ambiguous: bool
    native_session_id: str | None
    identity_error: str | None
    identity_scan: dict[str, object]


def run_sync(
    args: argparse.Namespace,
    *,
    api_url: str,
    client_id: str,
    source_path: str,
    log_fn: LogFn,
) -> int:
    with sync_lock():
        try:
            state = load_state()
        except (OSError, ValueError) as exc:
            log_fn(f"[WARN] Invalid Codex sync state: {exc}")
            return 2
        try:
            project_bindings = load_project_bindings()
        except (OSError, ValueError) as exc:
            log_fn(f"[WARN] Invalid Codex project binding snapshot: {exc}")
            return 2
        open_snapshot = discover_open_transcripts()
        infos = _transcript_infos(args, state, open_snapshot, log_fn)
        binding_request, binding_error = _project_binding_request(args, infos)
        if binding_error:
            log_fn(f"[WARN] {binding_error}")
            return 2
        bindings_changed, binding_error = _prepare_project_bindings(
            infos,
            project_bindings,
            binding_request,
        )
        if binding_error:
            log_fn(f"[WARN] {binding_error}")
            return 2
        if bindings_changed:
            # The local compare-and-set is the authority for Agent Hub's immutable
            # project field, so persist it before any remote session mutation.
            save_project_bindings_locked(project_bindings)
        live_transcript_paths, saw_live_codex_process = _live_session_context(
            args,
            open_snapshot,
            log_fn,
        )
        inherited_bindings_changed, binding_synced = _sync_infos(
            args=args,
            state=state,
            infos=infos,
            api_url=api_url,
            client_id=client_id,
            source_path=source_path,
            log_fn=log_fn,
            live_transcript_paths=live_transcript_paths,
            saw_live_codex_process=saw_live_codex_process,
            project_bindings=project_bindings,
            binding_request=binding_request,
        )
        if inherited_bindings_changed:
            save_project_bindings_locked(project_bindings)
        save_state(state)
        if binding_request is not None and not binding_synced:
            return 2
        return 0


def sync_transcript(
    info: TranscriptInfoLike,
    state: dict[str, object],
    api_url: str,
    client_id: str,
    source_path: str,
    close_session: bool,
    ingest_required: bool,
    heartbeat_required: bool,
    log_fn: LogFn,
    verbose: bool,
    project_binding: ProjectBinding | None = None,
    reactivate_open_session: bool = False,
) -> tuple[bool, str, int | None]:
    if info.identity_error:
        return False, info.identity_error, None
    project, effective_cwd, project_error, transcript_git_verified = (
        _resolve_project_context(info, project_binding)
    )
    if project_error:
        return False, project_error, None
    assert project is not None

    mapping_state, mapping_error = _project_mapping_state(
        info,
        project,
        explicitly_bound=project_binding is not None,
        transcript_git_verified=transcript_git_verified,
    )
    if mapping_error:
        return False, mapping_error, None
    meta = _session_meta(info, project, mapping_state, effective_cwd)
    identity_fingerprint = _identity_fingerprint(info, project, meta)
    project_binding_fingerprint = _project_binding_fingerprint(project_binding)
    kw = _sync_keywords(api_url, client_id, source_path)

    ok, err, status, project = _ensure_session_upserted(
        info,
        state,
        project,
        meta,
        identity_fingerprint,
        effective_cwd,
        kw,
        reactivate_open_session=reactivate_open_session,
    )
    if not ok:
        return False, err, status

    entry = get_state_entry(info.path, state) or {}
    same_transcript_identity = entry.get("session_id") == info.session_id
    checkpoint = (
        get_checkpoint(info.path, state)
        if same_transcript_identity
        else None
    )
    next_checkpoint = checkpoint
    # Carry the last success detail forward; a prior failure's text must not survive a success.
    prior_ok = entry.get("status") in {"active", "synced", "terminal"}
    detail = str(entry.get("detail") or "unchanged") if prior_ok else "unchanged"
    if ingest_required:
        ok, next_checkpoint, detail, err, status = ingest_transcript(
            info.session_id,
            info.path,
            checkpoint,
            **kw,
        )
        if not ok:
            return False, err, status

    heartbeat_at: str | None = None
    if heartbeat_required and not close_session:
        ok, err, status = send_heartbeat(info.session_id, effective_cwd, project, meta, **kw)
        if not ok:
            return False, err, status
        heartbeat_at = datetime.now(UTC).isoformat()
        if not ingest_required:
            detail = "heartbeat"

    if close_session:
        ok, err, status = finalize_and_close(info.session_id, project, True, **kw)
        if not ok:
            return False, err, status

    sync_status = "terminal" if close_session else ("active" if info.is_open else "synced")
    update_state_entry(
        state,
        info.path,
        info.session_id,
        info.mtime,
        info.size,
        sync_status,
        detail,
        checkpoint=next_checkpoint,
        preserve_checkpoint=same_transcript_identity,
        identity_fingerprint=identity_fingerprint,
        project_binding_fingerprint=project_binding_fingerprint,
        heartbeat_at=heartbeat_at,
        identity_scan=info.identity_scan,
    )
    if verbose:
        log_fn(
            f"[INFO] Synced session={info.session_id} project={project['project_id']} "
            f"transcript={info.path} ingest={ingest_required} heartbeat={heartbeat_required} "
            f"close={close_session}"
        )
    return True, "ok", None


def _resolve_project_context(
    info: TranscriptInfoLike,
    project_binding: ProjectBinding | None,
) -> tuple[dict[str, object] | None, Path, str, bool]:
    git_project_data = build_project_context(info.cwd)
    git_project = git_project_data if isinstance(git_project_data, dict) else None
    if project_binding is None:
        if git_project is None:
            return None, info.cwd, f"skip unmapped/unregistered cwd={info.cwd}", False
        return git_project, info.cwd, "", True

    bound_project_data = build_project_context(Path(project_binding.project_root))
    if not isinstance(bound_project_data, dict):
        return (
            None,
            info.cwd,
            "conflict invalid Codex thread project binding "
            f"project={project_binding.project_id} root={project_binding.project_root} ",
            False,
        )
    bound_project: dict[str, object] = bound_project_data
    bound_root = Path(str(bound_project.get("repo_root") or "")).resolve()
    stored_root = Path(project_binding.project_root).expanduser().resolve()
    if bound_root != stored_root or project_binding.project_id not in _project_ids(bound_project):
        return (
            None,
            info.cwd,
            "conflict stale Codex thread project binding "
            f"project={project_binding.project_id} root={project_binding.project_root}",
            False,
        )
    if git_project is not None and _project_ids(git_project).isdisjoint(_project_ids(bound_project)):
        return (
            None,
            info.cwd,
            "conflict Codex thread binding/Git project mismatch "
            f"binding={project_binding.project_id} git={git_project['project_id']} "
            f"transcript={info.path}",
            False,
        )
    return bound_project, bound_root, "", git_project is not None


def _project_ids(project: dict[str, object]) -> set[str]:
    identifiers = {str(project.get("project_id") or "")}
    aliases = project.get("project_aliases")
    if isinstance(aliases, list):
        identifiers.update(alias for alias in aliases if isinstance(alias, str) and alias)
    identifiers.discard("")
    return identifiers


def _project_binding_fingerprint(binding: ProjectBinding | None) -> str | None:
    if binding is None:
        return None
    canonical = {
        "project_id": binding.project_id,
        "project_root": str(Path(binding.project_root).expanduser().resolve()),
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _project_mapping_state(
    info: TranscriptInfoLike,
    project: dict[str, object],
    *,
    explicitly_bound: bool = False,
    transcript_git_verified: bool = False,
) -> tuple[str, str]:
    if info.ownership_ambiguous:
        return "ambiguous", f"conflict ambiguous AICO ownership transcript={info.path}"
    owner = info.process_owner
    if owner is None:
        return ("explicit_binding" if explicitly_bound else "git_only"), ""
    if explicitly_bound and (
        transcript_git_verified
        or owner.aico_project_id == AICO_PERSONAL_PROJECT_ID
    ):
        return "explicit_binding", ""

    project_id = str(project["project_id"])
    aliases = {
        alias
        for alias in project.get("project_aliases", [])
        if isinstance(alias, str) and alias
    }
    if not owner.aico_project_id:
        return (
            "unmapped",
            f"conflict AICO owner has no project mapping transcript={info.path}",
        )
    if owner.aico_project_id not in {project_id, *aliases}:
        return (
            "mismatch",
            "conflict AICO/Git project mismatch "
            f"aico={owner.aico_project_id} git={project_id} transcript={info.path}",
        )
    return ("explicit_binding" if explicitly_bound else "matched"), ""


def _session_meta(
    info: TranscriptInfoLike,
    project: dict[str, object],
    project_mapping_state: str,
    effective_cwd: Path,
) -> dict[str, object]:
    owner = info.process_owner
    harness = owner.harness if owner is not None else "codex"
    return {
        "native_session_id": info.native_session_id,
        "transcript_path": str(info.path),
        "repo_root": project["repo_root"],
        "cwd": str(effective_cwd),
        "host": os.uname().nodename,
        "external_identity": {
            "harness": harness,
            "launcher": "aico" if owner is not None else "direct",
            "display_identity": info.agent_nickname or harness,
            "runtime_session_id": info.session_id,
            "agent_path": external_agent_path(info),
            "aico_session_id": owner.aico_session_id if owner is not None else None,
            "aico_widget_id": owner.aico_widget_id if owner is not None else None,
            "aico_project_id": owner.aico_project_id if owner is not None else None,
            "project_mapping_state": project_mapping_state,
        },
    }


def _identity_fingerprint(
    info: TranscriptInfoLike,
    project: dict[str, object],
    meta: dict[str, object],
) -> str:
    canonical = {
        "session_id": info.session_id,
        "parent_session_id": info.parent_session_id,
        "project_id": project["project_id"],
        "external_identity": meta["external_identity"],
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sync_keywords(api_url: str, client_id: str, source_path: str) -> dict[str, str]:
    return {
        "api_url": api_url,
        "client_id": client_id,
        "source_path": source_path,
    }


def _ensure_session_upserted(
    info: TranscriptInfoLike,
    state: dict[str, object],
    project: dict[str, object],
    meta: dict[str, object],
    identity_fingerprint: str,
    effective_cwd: Path,
    kw: dict[str, str],
    *,
    reactivate_open_session: bool = False,
) -> tuple[bool, str, int | None, dict[str, object]]:
    entry = get_state_entry(info.path, state)
    if not _should_upsert(
        entry,
        info.session_id,
        identity_fingerprint,
        is_open=info.is_open,
        reactivate_open_session=reactivate_open_session,
    ):
        return True, "", None, project
    return _upsert_with_project_aliases(
        info=info,
        project=project,
        meta=meta,
        effective_cwd=effective_cwd,
        kw=kw,
    )


def _resolve_transcript_path(path: Path) -> Path:
    try:
        return path.expanduser().resolve(strict=False)
    except OSError:
        return path.expanduser()


def _close_inactive_session(
    info: TranscriptInfoLike,
    *,
    close_all: bool,
    close_inactive: bool,
    live_transcript_paths: set[Path],
    saw_live_codex_process: bool,
) -> bool:
    if close_all:
        return True
    if not close_inactive:
        return False
    if saw_live_codex_process and not live_transcript_paths:
        return False
    return _resolve_transcript_path(info.path) not in live_transcript_paths


def _should_upsert(
    entry: dict[str, object] | None,
    session_id: str,
    identity_fingerprint: str,
    *,
    is_open: bool,
    reactivate_open_session: bool = False,
) -> bool:
    if entry is None:
        return True
    if (
        is_open
        and entry.get("session_id") == session_id
        and (
            entry.get("status") == "terminal"
            or reactivate_open_session
        )
    ):
        # A restarted client can continue writing the exact native transcript
        # after an earlier process marked its Agent Hub row complete.  The open
        # file identity is the authority for reactivating that same session.
        return True
    if (
        not is_open
        and entry.get("session_id") == session_id
        and entry.get("identity_fingerprint")
        and entry.get("status") in {"active", "synced", "terminal"}
    ):
        # A closed process no longer exposes its AICO environment.  Preserve the
        # richer identity previously recorded while it was live instead of
        # replacing it with a synthetic direct-launch identity during closeout.
        return False
    return not (
        entry.get("session_id") == session_id
        and entry.get("identity_fingerprint") == identity_fingerprint
        and entry.get("status") in {"active", "synced", "terminal"}
    )


def _upsert_with_project_aliases(
    *,
    info: TranscriptInfoLike,
    project: dict[str, object],
    meta: dict[str, object],
    effective_cwd: Path,
    kw: dict[str, str],
) -> tuple[bool, str, int | None, dict[str, object]]:
    candidates = [project, *_project_aliases(project)]
    last_err = ""
    last_status: int | None = None
    for candidate in candidates:
        ok, err, status = upsert_session(
            info.session_id,
            candidate,
            info.model,
            effective_cwd,
            info.path,
            parent_session_id=info.parent_session_id,
            provider_metadata=meta,
            **kw,
        )
        if ok:
            return True, "", status, candidate
        last_err = err
        last_status = status
        if status != 400 or "Unknown project_id" not in err:
            break
    return False, last_err, last_status, project


def _project_aliases(project: dict[str, object]) -> list[dict[str, object]]:
    aliases = project.get("project_aliases")
    if not isinstance(aliases, list):
        return []
    candidates: list[dict[str, object]] = []
    for alias in aliases:
        if not isinstance(alias, str) or not alias:
            continue
        alias_project = dict(project)
        alias_project["project_id"] = alias
        candidates.append(alias_project)
    return candidates


def _transcript_infos(
    args: argparse.Namespace,
    state: dict[str, object],
    open_snapshot: OpenTranscriptSnapshot,
    log_fn: LogFn,
) -> list[TranscriptInfoLike]:
    if args.transcript is not None:
        info = read_transcript_info(
            args.transcript,
            log_fn=log_fn,
            open_snapshot=open_snapshot,
            scan_state=(get_state_entry(_resolve_transcript_path(args.transcript), state) or {}).get("identity_scan") or (get_state_entry(_resolve_transcript_path(args.transcript), state) or {}).get("model_scan"),
        )
        infos: list[TranscriptInfoLike] = [info] if info is not None else []
    else:
        recent = iter_recent_transcripts(
            args.recent_hours,
            log_fn=log_fn,
            open_snapshot=open_snapshot,
            scan_states=state.get("transcripts"),
        )
        by_path: dict[Path, TranscriptInfoLike] = {
            _resolve_transcript_path(info.path): info for info in recent
        }
        candidates = set(open_snapshot.paths)
        if args.close_inactive:
            candidates.update(iter_nonterminal_paths(state))
        for path in sorted(candidates):
            resolved = _resolve_transcript_path(path)
            if resolved in by_path:
                continue
            info = read_transcript_info(path, log_fn=log_fn, open_snapshot=open_snapshot,
                scan_state=((get_state_entry(resolved, state) or {}).get("identity_scan") or (get_state_entry(resolved, state) or {}).get("model_scan")))
            if info is not None:
                by_path[resolved] = info
        infos = list(by_path.values())

    if args.cwd is not None:
        target_cwd = args.cwd.expanduser().resolve()
        infos = [info for info in infos if info.cwd.expanduser().resolve() == target_cwd]
    bind_session = getattr(args, "bind_session", None)
    if isinstance(bind_session, str) and bind_session:
        infos = [info for info in infos if info.session_id == bind_session]
    return _parents_before_children(infos)


def _parents_before_children(infos: list[TranscriptInfoLike]) -> list[TranscriptInfoLike]:
    by_session = {info.session_id: info for info in infos}
    depths: dict[str, int] = {}

    def depth(session_id: str, trail: frozenset[str] = frozenset()) -> int:
        if session_id in depths:
            return depths[session_id]
        if session_id in trail:
            return len(infos) + 1
        info = by_session[session_id]
        parent_id = info.parent_session_id
        value = 0
        if parent_id in by_session:
            value = 1 + depth(parent_id, trail | {session_id})
        depths[session_id] = value
        return value

    return sorted(
        infos,
        key=lambda info: (depth(info.session_id), info.mtime, info.session_id),
    )


def _live_session_context(
    args: argparse.Namespace,
    open_snapshot: OpenTranscriptSnapshot,
    log_fn: LogFn,
) -> tuple[set[Path], bool]:
    live_transcript_paths = set(open_snapshot.paths)
    if not args.close_inactive:
        return live_transcript_paths, False
    saw_live_codex_process = has_live_codex_process()
    if saw_live_codex_process and not live_transcript_paths:
        log_fn(
            "[WARN] Live Codex process found but no open transcript files detected; "
            "skipping inactive session close pass"
        )
    return live_transcript_paths, saw_live_codex_process


def _project_binding_request(
    args: argparse.Namespace,
    infos: list[TranscriptInfoLike],
) -> tuple[ProjectBinding | None, str]:
    session_id = getattr(args, "bind_session", None)
    project_id = getattr(args, "bind_project", None)
    project_root = getattr(args, "project_root", None)
    values = (session_id, project_id, project_root)
    if not any(value is not None for value in values):
        return None, ""
    if not all(value is not None for value in values):
        return None, "binding requires --bind-session, --bind-project, and --project-root"
    assert isinstance(session_id, str)
    assert isinstance(project_id, str)
    root = Path(project_root).expanduser().resolve()
    matches = [info for info in infos if info.session_id == session_id]
    if len(matches) != 1:
        return None, f"live Codex transcript not found for session={session_id}"
    info = matches[0]
    if info.identity_error:
        return None, info.identity_error
    if not info.is_open:
        return None, f"Codex transcript is not open for session={session_id}"
    if info.ownership_ambiguous:
        return None, f"conflict ambiguous AICO ownership transcript={info.path}"
    registered_root = fetch_registered_project_root(project_id)
    if registered_root is None:
        return None, f"project is not registered in SummitFlow: {project_id}"
    if registered_root != root:
        return (
            None,
            f"registered project root mismatch requested={root} registered={registered_root}",
        )
    project_data = build_project_context(root)
    if not isinstance(project_data, dict):
        return None, f"registered project root is not a Git checkout: {root}"
    canonical_root = Path(str(project_data.get("repo_root") or "")).resolve()
    if canonical_root != root:
        return None, f"project root must be the canonical Git root: {canonical_root}"
    if project_id not in _project_ids(project_data):
        return (
            None,
            f"project id/root mismatch requested={project_id} "
            f"canonical={project_data.get('project_id')}",
        )
    git_project_data = build_project_context(info.cwd)
    if isinstance(git_project_data, dict) and _project_ids(git_project_data).isdisjoint(
        _project_ids(project_data)
    ):
        return (
            None,
            "conflict Codex thread binding/Git project mismatch "
            f"binding={project_data['project_id']} git={git_project_data['project_id']} "
            f"transcript={info.path}",
        )
    _, mapping_error = _project_mapping_state(
        info,
        project_data,
        explicitly_bound=True,
        transcript_git_verified=isinstance(git_project_data, dict),
    )
    if mapping_error:
        return None, mapping_error
    return (
        ProjectBinding(
            session_id=session_id,
            project_id=str(project_data["project_id"]),
            project_root=str(canonical_root),
            bound_at=datetime.now(UTC).isoformat(),
            source="explicit",
            parent_session_id=None,
        ),
        "",
    )


def _same_binding_target(left: ProjectBinding, right: ProjectBinding) -> bool:
    return (
        left.project_id == right.project_id
        and Path(left.project_root).expanduser().resolve()
        == Path(right.project_root).expanduser().resolve()
    )


def _effective_project_binding(
    info: TranscriptInfoLike,
    project_bindings: dict[str, ProjectBinding],
    binding_request: ProjectBinding | None,
) -> tuple[ProjectBinding | None, bool, str]:
    if info.identity_error:
        return None, False, info.identity_error
    existing = project_bindings.get(info.session_id)
    requested = binding_request if binding_request and binding_request.session_id == info.session_id else None
    if existing is not None and requested is not None and not _same_binding_target(existing, requested):
        return (
            None,
            False,
            "conflict immutable Codex thread project binding "
            f"session={info.session_id} existing={existing.project_id} "
            f"requested={requested.project_id}",
        )
    own = requested or existing
    parent = (
        project_bindings.get(info.parent_session_id)
        if isinstance(info.parent_session_id, str) and info.parent_session_id
        else None
    )
    if own is not None and parent is not None and not _same_binding_target(own, parent):
        return (
            None,
            False,
            "conflict Codex child/parent project binding mismatch "
            f"child={info.session_id}:{own.project_id} "
            f"parent={info.parent_session_id}:{parent.project_id}",
        )
    if own is not None:
        return own, requested is not None and existing is None, ""
    if parent is None:
        return None, False, ""
    inherited = ProjectBinding(
        session_id=info.session_id,
        project_id=parent.project_id,
        project_root=parent.project_root,
        bound_at=datetime.now(UTC).isoformat(),
        source="inherited",
        parent_session_id=info.parent_session_id,
    )
    return inherited, True, ""


def _prepare_project_bindings(
    infos: list[TranscriptInfoLike],
    project_bindings: dict[str, ProjectBinding],
    binding_request: ProjectBinding | None,
) -> tuple[bool, str]:
    """Persist the immutable root/child binding graph before remote mutation."""
    changed = False
    if binding_request is not None:
        existing = project_bindings.get(binding_request.session_id)
        if existing is not None and not _same_binding_target(existing, binding_request):
            return (
                False,
                "conflict immutable Codex thread project binding "
                f"session={binding_request.session_id} existing={existing.project_id} "
                f"requested={binding_request.project_id}",
            )
        for child in project_bindings.values():
            if child.parent_session_id != binding_request.session_id:
                continue
            if not _same_binding_target(child, binding_request):
                return (
                    False,
                    "conflict Codex child/parent project binding mismatch "
                    f"child={child.session_id}:{child.project_id} "
                    f"parent={binding_request.session_id}:{binding_request.project_id}",
                )
        if existing is None:
            project_bindings[binding_request.session_id] = binding_request
            changed = True

    for info in infos:
        project_binding, should_store, binding_error = _effective_project_binding(
            info,
            project_bindings,
            binding_request,
        )
        if binding_error:
            if binding_request is not None:
                return False, binding_error
            continue
        if should_store and project_binding is not None:
            project_bindings[info.session_id] = project_binding
            changed = True
    return changed, ""


def _sync_infos(
    *,
    args: argparse.Namespace,
    state: dict[str, object],
    infos: list[TranscriptInfoLike],
    api_url: str,
    client_id: str,
    source_path: str,
    log_fn: LogFn,
    live_transcript_paths: set[Path],
    saw_live_codex_process: bool,
    project_bindings: dict[str, ProjectBinding] | None = None,
    binding_request: ProjectBinding | None = None,
) -> tuple[bool, bool]:
    bindings = project_bindings if project_bindings is not None else {}
    bindings_changed = False
    binding_synced = False
    failed_session_ids: set[str] = set()
    for info in infos:
        if info.parent_session_id in failed_session_ids:
            log_fn(
                "[WARN] Deferred Codex child sync until parent succeeds "
                f"child={info.session_id} parent={info.parent_session_id}"
            )
            continue
        project_binding, should_store_binding, binding_error = _effective_project_binding(
            info,
            bindings,
            binding_request,
        )
        if binding_error:
            _record_sync_error(state, info, binding_error, None, log_fn)
            failed_session_ids.add(info.session_id)
            continue
        binding_fingerprint = _project_binding_fingerprint(project_binding)
        entry = get_state_entry(info.path, state) or {}
        rejected_identity = _rejection_identity(info, client_id)
        identity_changed = (
            entry_is_permanent_error(entry)
            and entry.get("rejected_identity") is not None
            and entry["rejected_identity"] != rejected_identity
        )
        if entry_is_permanent_error(entry) and entry.get("rejected_identity") is None:
            # Baseline legacy rejected rows without causing a migration retry storm.
            entry["rejected_identity"] = rejected_identity
        binding_changed = (
            binding_fingerprint is not None
            and entry.get("project_binding_fingerprint") != binding_fingerprint
        )
        close_session = _close_inactive_session(
            info,
            close_all=args.close,
            close_inactive=args.close_inactive,
            live_transcript_paths=live_transcript_paths,
            saw_live_codex_process=saw_live_codex_process,
        )
        ingest_required = should_sync(
            info.path,
            info.mtime,
            info.size,
            state,
            args.force or binding_changed or identity_changed,
        )
        close_required = close_session and should_sync(
            info.path,
            info.mtime,
            info.size,
            state,
            args.force or binding_changed or identity_changed,
            close_session=True,
        )
        heartbeat_required = (
            info.is_open
            and not close_session
            and should_heartbeat(info.path, state, force=args.force or binding_changed or identity_changed)
        )
        if not ingest_required and not close_required and not heartbeat_required:
            continue
        ok, detail, status = sync_transcript(
            info=info,
            state=state,
            api_url=api_url,
            client_id=client_id,
            source_path=source_path,
            close_session=close_required,
            ingest_required=ingest_required,
            heartbeat_required=heartbeat_required,
            log_fn=log_fn,
            verbose=args.verbose,
            project_binding=project_binding,
            reactivate_open_session=(
                binding_request is not None
                and info.session_id == binding_request.session_id
                and info.is_open
            ),
        )
        if ok:
            if should_store_binding and project_binding is not None:
                bindings[info.session_id] = project_binding
                bindings_changed = True
            if binding_request is not None and info.session_id == binding_request.session_id:
                binding_synced = True
            continue
        if detail.startswith("skip "):
            _record_skipped(state, info, detail, log_fn)
        else:
            _record_sync_error(
                state,
                info,
                detail,
                status,
                log_fn,
                project_binding_fingerprint=binding_fingerprint,
                rejected_identity=rejected_identity,
            )
        failed_session_ids.add(info.session_id)
    return bindings_changed, binding_synced


def _record_skipped(
    state: dict[str, object],
    info: TranscriptInfoLike,
    detail: str,
    log_fn: LogFn,
) -> None:
    repeated = _same_outcome(state, info, "skipped", detail)
    update_state_entry(
        state,
        info.path,
        info.session_id,
        info.mtime,
        info.size,
        "skipped",
        detail,
    )
    if not repeated:
        log_fn(f"[WARN] {detail} transcript={info.path}")


def _same_outcome(state: dict[str, object], info: TranscriptInfoLike, status: str, detail: str) -> bool:
    """True when an unchanged transcript repeats its recorded outcome.

    The timer retries every 15 seconds; warning again for each unchanged
    failure filled the journal and syslog (2026-10-10, ~1.8 GB/day).
    """
    entry = get_state_entry(info.path, state) or {}
    return (
        entry.get("status") == status
        and entry.get("detail") == detail
        and entry.get("mtime") == info.mtime
        and entry.get("size") == info.size
    )


def _record_sync_error(
    state: dict[str, object],
    info: TranscriptInfoLike,
    detail: str,
    status: int | None,
    log_fn: LogFn,
    *,
    project_binding_fingerprint: str | None = None,
    rejected_identity: str | None = None,
) -> None:
    outcome = "permanent_error" if status in PERMANENT_HTTP_STATUSES else "error"
    repeated = _same_outcome(state, info, outcome, detail)
    update_state_entry(
        state,
        info.path,
        info.session_id,
        info.mtime,
        info.size,
        outcome,
        detail,
        project_binding_fingerprint=project_binding_fingerprint,
        rejected_identity=rejected_identity,
    )
    if not repeated:
        log_fn(f"[WARN] Failed sync for {info.path}: {detail}")


def _rejection_identity(info: TranscriptInfoLike, client_id: str) -> str:
    """Only identity inputs can reopen a rejected request; file growth cannot."""
    owner = info.process_owner
    identity = {
        "client_id": client_id, "session_id": info.session_id, "cwd": str(info.cwd),
        "model": info.model, "parent": info.parent_session_id,
        "agent_path": info.agent_path, "agent_nickname": info.agent_nickname,
        "aico_session_id": owner.aico_session_id if owner else None,
        "aico_widget_id": owner.aico_widget_id if owner else None,
        "aico_project_id": owner.aico_project_id if owner else None,
    }
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
