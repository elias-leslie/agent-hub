"""CLI wrapper for Agent Hub runtime context rendering."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from app.db import async_session
from app.services.runtime_context import (
    CanonicalContextDeliveryRequest,
    build_canonical_context_delivery,
    render_runtime_context,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render runtime context for external agentic CLIs.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("sync-opencode", help="Ingest an OpenCode native export from stdin.")

    retire = subparsers.add_parser("retire-opencode", help="Finalize OpenCode sessions for an exactly retired Tether ownership ID.")
    retire.add_argument("--aico-session", required=True)

    retire_pi = subparsers.add_parser("retire-pi", help="Finalize Pi sessions for an exactly retired Tether ownership ID.")
    retire_pi.add_argument("--aico-session", required=True)

    sync = subparsers.add_parser("sync-pi", help="Ingest a native Pi transcript without model calls.")
    for field in ("session", "transcript", "cwd", "provider", "model"):
        sync.add_argument("--" + field, required=True)
    sync.add_argument("--project")
    sync.add_argument("--phase", choices=("idle", "working", "shutdown"), default="idle")
    sync.add_argument("--aico-session")
    sync.add_argument("--work-role-json", help="Explicit immutable launch declaration")

    bind = subparsers.add_parser("bind-native-work-role", help="Bind an explicit launch role to its native session.")
    bind.add_argument("--surface", required=True, choices=("codex", "claude_code"))
    bind.add_argument("--session", required=True)
    bind.add_argument("--cwd", required=True)
    bind.add_argument("--project")
    bind.add_argument("--model")
    bind.add_argument("--work-role-json", required=True)

    maintenance = subparsers.add_parser("maintenance", help="Inspect retained historical context maintenance records.")
    maintenance.add_argument("--request-file", help="JSON MaintenanceRequest file; use - for stdin. Omit to list relevant items.")
    maintenance.add_argument("--project")
    maintenance.add_argument("--surface", default="codex")
    maintenance.add_argument("--session", help="Stable native session ID for claims and explicit acknowledgment")
    maintenance.add_argument("--agent-slug")
    maintenance.add_argument("--profile", default="agent_startup")
    maintenance.add_argument("--workflow", action="append", default=[])
    maintenance.add_argument("--task-type")
    maintenance.add_argument("--phase")
    maintenance.add_argument("--consumer-tag", action="append", default=[])
    maintenance.add_argument("--include-background", action="store_true")
    maintenance.add_argument("--include-closed", action="store_true")
    maintenance.add_argument("--schema", action="store_true", help="Show the exact action schema and evidence requirements")

    deliver_parser = subparsers.add_parser(
        "deliver",
        help="Deliver the canonical additive Agent Hub context contract.",
    )
    deliver_parser.add_argument("--surface", required=True, help="Consumer surface name")
    deliver_parser.add_argument(
        "--profile",
        "--consumer-profile",
        dest="consumer_profile",
        default="agent_startup",
    )
    deliver_parser.add_argument("--capability", action="append", default=[])
    deliver_parser.add_argument("--agent-slug", help="Agent Hub agent applicability slug")
    deliver_parser.add_argument(
        "--consumer-tag",
        action="append",
        default=[],
        help="Explicit applicability audience tag; repeatable",
    )
    deliver_parser.add_argument("--workflow", action="append", default=[], help="Explicitly activate a workflow for this delivery/session")
    deliver_parser.add_argument("--source-id", action="append", default=[], help="Retrieve an applicable on-demand source")
    deliver_parser.add_argument("--project", help="Canonical project ID")
    deliver_parser.add_argument("--session", help="Consumer session ID")
    deliver_parser.add_argument("--task", help="Current task or initial prompt")
    deliver_parser.add_argument("--query", help="Task-aware context selection query")
    deliver_parser.add_argument("--task-type", help="Optional task type")
    deliver_parser.add_argument("--phase", help="Optional lifecycle phase")
    deliver_parser.add_argument("--branch", help="Current git branch")
    deliver_parser.add_argument("--cwd", help="Consumer working directory")
    deliver_parser.add_argument("--repo-root", help="Canonical repository root")
    deliver_parser.add_argument("--provider", help="Consumer provider label")
    deliver_parser.add_argument("--model", help="Consumer model label")
    deliver_parser.add_argument("--variant", help="Optional memory-selection variant")
    deliver_parser.add_argument("--optional-context", choices=("on", "off"), default="on",
                                help="Off omits advisory context, indexes, guidance and continuity; required policy remains")
    deliver_parser.add_argument("--hook-event", help="Native hook event name")
    deliver_parser.add_argument("--source", help="Native launch source")
    deliver_parser.add_argument("--turn-id", help="Native turn ID")
    deliver_parser.add_argument("--subagent-id", help="Native subagent ID")
    deliver_parser.add_argument("--subagent-type", help="Native subagent type")
    deliver_parser.add_argument(
        "--metadata",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Additional client metadata; repeatable",
    )
    deliver_parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output exact rendered text or the full versioned contract",
    )

    feedback_parser = subparsers.add_parser("feedback", help="Record optional structured context feedback")
    for argument in ("source-type", "source-id", "source-revision", "session-id", "turn-id", "assessment", "evidence"):
        feedback_parser.add_argument("--" + argument, required=True)

    render_parser = subparsers.add_parser("render", help="Render formatted runtime context.")
    render_parser.add_argument("query_arg", nargs="?", help="Selection query")
    render_parser.add_argument("--query", help="Selection query")
    render_parser.add_argument("--consumer-profile", default="agent_startup")
    render_parser.add_argument("--project", help="Optional project ID")
    render_parser.add_argument("--task-type", help="Optional task type")
    render_parser.add_argument("--phase", help="Optional phase")
    render_parser.add_argument("--json", action="store_true", help="Emit full JSON payload")

    status_parser = subparsers.add_parser("status", help="Probe runtime context rendering.")
    status_parser.add_argument("--consumer-profile", default="agent_startup")
    status_parser.add_argument("--project", help="Optional project ID")
    status_parser.add_argument("--query", default="startup context")
    status_parser.add_argument("--json", action="store_true")
    return parser


def _resolve_query(explicit: str | None, positional: str | None) -> str:
    if explicit:
        return explicit.strip()
    if positional:
        return positional.strip()
    return sys.stdin.read().strip() or "startup context"


async def _render(args: argparse.Namespace):
    async with async_session() as db:
        return await render_runtime_context(
            db,
            consumer_profile=args.consumer_profile,
            project_id=(args.project or "").strip() or None,
            query=_resolve_query(getattr(args, "query", None), getattr(args, "query_arg", None)),
            task_type=getattr(args, "task_type", None),
            phase=getattr(args, "phase", None),
        )


def _parse_metadata(values: list[str]) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for raw in values:
        key, separator, value = raw.partition("=")
        key = key.strip()
        if not separator or not key:
            raise ValueError(f"Invalid --metadata value {raw!r}; expected KEY=VALUE")
        metadata[key] = value
    return metadata


async def _deliver(args: argparse.Namespace):
    client_metadata = _parse_metadata(args.metadata)
    for key, value in (
        ("hook_event_name", args.hook_event),
        ("source", args.source),
        ("turn_id", args.turn_id),
        ("subagent_id", args.subagent_id),
        ("subagent_type", args.subagent_type),
    ):
        if value:
            client_metadata[key] = value

    request = CanonicalContextDeliveryRequest(
        consumer_surface=args.surface,
        consumer_profile=args.consumer_profile,
        capabilities=args.capability,
        agent_slug=(args.agent_slug or "").strip() or None,
        consumer_tags=args.consumer_tag,
        workflow_ids=args.workflow,
        requested_source_ids=args.source_id,
        project_id=(args.project or "").strip() or None,
        session_id=(args.session or "").strip() or None,
        task=args.task,
        query=args.query,
        task_type=args.task_type,
        phase=args.phase,
        current_branch=args.branch,
        cwd=args.cwd,
        repo_root=args.repo_root,
        provider=args.provider,
        model=args.model,
        variant=args.variant,
        client_metadata=client_metadata,
        include_references=args.optional_context != "off",
        include_reference_index=args.optional_context != "off",
        include_project_index=args.optional_context != "off",
        include_tool_capabilities=args.optional_context != "off",
        include_continuity=args.optional_context != "off",
    )
    async with async_session() as db:
        return await build_canonical_context_delivery(db, request)


async def _feedback(args: argparse.Namespace) -> dict:
    from app.services.context_governance import ContextFeedback, record_feedback
    request = ContextFeedback(**{key: value for key, value in vars(args).items() if key != "command"}, actor_type="agent")
    async with async_session() as db:
        return await record_feedback(db, request, "agent:native-cli")


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "bind-native-work-role":
        try:
            asyncio.run(_bind_native_work_role(args))
            return 0
        except Exception:
            print("Native session work role registration unavailable", file=sys.stderr)
            return 2
    if args.command in {"retire-opencode", "retire-pi"}:
        surface_name = "Pi" if args.command == "retire-pi" else "OpenCode"
        try:
            from app.services.session_ingestion.opencode_sync import retire_opencode_sessions
            from app.services.session_ingestion.pi_sync import retire_pi_sessions
            async def run_retirement() -> dict:
                async with async_session() as db:
                    retire_sessions = retire_pi_sessions if args.command == "retire-pi" else retire_opencode_sessions
                    return await retire_sessions(db, args.aico_session)
            print(json.dumps(asyncio.run(run_retirement())))
            return 0
        except Exception:
            print(f"{surface_name} retirement sync unavailable", file=sys.stderr)
            return 2
    if args.command == "sync-opencode":
        try:
            from app.services.session_ingestion.opencode_sync import sync_opencode_export
            payload = json.loads(sys.stdin.read(16 * 1024 * 1024 + 1))
            async def run_sync() -> dict:
                async with async_session() as db:
                    return await sync_opencode_export(db, payload)
            print(json.dumps(asyncio.run(run_sync())))
            return 0
        except Exception:
            print("OpenCode session sync unavailable", file=sys.stderr)
            return 2
    if args.command == "sync-pi":
        try:
            print(json.dumps(asyncio.run(_sync_pi(args))))
            return 0
        except Exception:
            # Database exceptions can contain private connection information.
            print("Pi session sync unavailable", file=sys.stderr)
            return 2
    if args.command == "maintenance":
        from app.services.context_maintenance_actions import MaintenanceRequest
        if args.schema:
            print(json.dumps(MaintenanceRequest.model_json_schema(), indent=2))
            return 0
        print(json.dumps(asyncio.run(_maintenance(args)), indent=2))
        return 0
    if args.command == "feedback":
        print(json.dumps(asyncio.run(_feedback(args))))
        return 0
    if args.command == "deliver":
        try:
            response = asyncio.run(_deliver(args))
        except ValueError as exc:
            parser.error(str(exc))
        if args.format == "json":
            print(json.dumps(response.model_dump(mode="json"), indent=2, sort_keys=True))
        else:
            # stdout bytes exactly match the bytes covered by payload_hash.
            sys.stdout.write(response.rendered)
        return 0 if response.status == "ok" else 2

    response = asyncio.run(_render(args))
    if getattr(args, "json", False):
        print(json.dumps(response.model_dump(mode="json"), indent=2, sort_keys=True))
    elif args.command == "status":
        print(
            f"runtime_context={response.status.upper()} profile={response.consumer_profile} "
            f"project={response.project_id or '-'} blocks={len(response.blocks)} "
            f"tokens={response.total_tokens}"
        )
    else:
        chunks = [
            response.rendered,
            response.project_index,
            response.continuity,
            response.tool_capabilities,
            response.non_negotiables,
        ]
        print("\n".join(chunk for chunk in chunks if chunk))
    return 0 if response.status == "ok" else 2


async def _sync_pi(args: argparse.Namespace) -> dict:
    from app.services.runtime_context import _resolve_canonical_project_id
    from app.services.session_ingestion.pi_sync import sync_pi_session

    project_id = await _resolve_canonical_project_id(CanonicalContextDeliveryRequest(
        consumer_surface="pi", project_id=args.project, cwd=args.cwd))
    if not project_id:
        raise ValueError("Pi session cwd is outside registered projects")
    async with async_session() as db:
        return await sync_pi_session(db, session_id=args.session, transcript=args.transcript,
            project_id=project_id, cwd=args.cwd, provider=args.provider, model=args.model,
            phase=args.phase, aico_session_id=args.aico_session,
            work_role=json.loads(args.work_role_json) if args.work_role_json else None)


async def _bind_native_work_role(args: argparse.Namespace) -> None:
    import uuid

    from sqlalchemy import select

    from app.models import Session
    from app.services.runtime_context import _resolve_canonical_project_id
    from app.services.session_ingestion import SessionUpsertRequest, upsert_session

    # A supported native hook supplies the actual UUID. Correlation labels
    # (including AICO_SESSION_ID) are never accepted as session subjects.
    if str(uuid.UUID(args.session)) != args.session:
        raise ValueError("Expected exact native UUID")
    project_id = await _resolve_canonical_project_id(CanonicalContextDeliveryRequest(
        consumer_surface=args.surface, project_id=args.project, cwd=args.cwd))
    if not project_id:
        raise ValueError("Native session cwd is outside registered projects")
    async with async_session() as db:
        existing = (await db.execute(select(Session).where(Session.id == args.session))).scalar_one_or_none()
        if existing is not None and existing.parent_session_id is not None:
            return  # A native child never inherits its launcher's declaration.
        # Preserve the native producer's provider/model and existing identity.
        # Role immutability and provenance are enforced by canonical upsert.
        provider = existing.provider if existing else ("codex" if args.surface == "codex" else "anthropic")
        await upsert_session(db, SessionUpsertRequest(
            session_id=args.session, project_id=project_id, provider=provider,
            model=existing.model if existing else (args.model or f"{provider}/unknown"),
            session_type=existing.session_type if existing else ("agent" if args.surface == "codex" else "claude_code"),
            parent_session_id=existing.parent_session_id if existing else None,
            cwd=args.cwd, request_source="native-session-start",
            provider_metadata={"work_role": json.loads(args.work_role_json),
                               "harness": "codex_cli" if args.surface == "codex" else "claude_code"},
        ))


async def _maintenance(args: argparse.Namespace) -> dict:
    from pathlib import Path

    from app.services.context_maintenance_actions import MaintenanceRequest, handle_maintenance
    if args.request_file:
        raw = await asyncio.to_thread(sys.stdin.read if args.request_file == "-" else Path(args.request_file).read_text)
        request = MaintenanceRequest.model_validate_json(raw)
    else:
        request = MaintenanceRequest(context=CanonicalContextDeliveryRequest(consumer_surface=args.surface,
            project_id=args.project, session_id=args.session, agent_slug=args.agent_slug,
            consumer_profile=args.profile, workflow_ids=args.workflow, task_type=args.task_type, phase=args.phase, consumer_tags=args.consumer_tag), include_closed=args.include_closed, include_background=args.include_background)
    async with async_session() as db:
        if request.action in {"review", "reconcile", "repair", "apply", "resolve", "dismiss"}:
            from app.services.credential_manager import get_credential_manager
            await get_credential_manager().load(db)
        return await handle_maintenance(db, request, "agent:native-cli")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
