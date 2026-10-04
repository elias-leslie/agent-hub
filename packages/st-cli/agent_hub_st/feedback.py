"""Feedback commands for the CLI - agent feedback on infrastructure components."""

from __future__ import annotations

from typing import Annotated

import typer
from st_sdk.usage import usage

from .feedback_commands import (
    archive_impl,
    delete_impl,
    get_impl,
    link_impl,
    list_impl,
    merge_impl,
    references_impl,
    report_impl,
    resolve_impl,
    search_impl,
    summary_impl,
    vote_impl,
)

app = typer.Typer(
    name="feedback",
    help="Agent feedback system: report friction, ideas, improvements, and praise.",
    no_args_is_help=True,
)


@app.command("report")
@usage(
    surface="st.feedback.report",
    cmd="st feedback report <component> 'desc' --type friction|idea|improvement|praise",
    when="friction, idea, improvement, or praise discovered during work",
    precautions=(
        "components: sf.cli sf.dt sf.quality sf.worktree sf.api sf.storage sf.workflows sf.explorer sf.frontend sf.scripts ah.memory ah.completion ah.sessions ah.hooks xc.tool_registry xc.error_handling xc.testing",
        "inline alt: [[F:type:component:desc]]",
    ),
    tier="reference",
)
def report(
    component_id: Annotated[str, typer.Argument(help="Component ID (e.g. sf.cli, ah.memory)")],
    title: Annotated[str, typer.Argument(help="Short descriptive title")],
    feedback_type: Annotated[
        str, typer.Option("--type", "-t", help="Type: friction, idea, improvement, praise")
    ] = "friction",
    severity: Annotated[
        str | None, typer.Option("--severity", "-s", help="Severity: low, medium, high (friction only)")
    ] = None,
    description: Annotated[
        str | None, typer.Option("--desc", "-d", help="Detailed description")
    ] = None,
    project_id: Annotated[
        str, typer.Option("--project", "-p", help="Project ID")
    ] = "summitflow",
    session_id: Annotated[
        str | None, typer.Option("--session", help="Session ID of the reporter")
    ] = None,
    agent_slug: Annotated[
        str | None, typer.Option("--agent", help="Agent slug")
    ] = None,
    model_used: Annotated[
        str | None, typer.Option("--model", help="Model used")
    ] = None,
    session_type: Annotated[
        str | None, typer.Option("--session-type", help="Session type")
    ] = None,
    vote_if_match: Annotated[
        bool,
        typer.Option(
            "--vote-if-match/--no-vote-if-match",
            help="Vote on the strongest duplicate candidate instead of creating a new item",
        ),
    ] = False,
    occurrence_id: Annotated[str | None, typer.Option("--occurrence", help="Stable observation ID; reuse for retries and relays")] = None,
    source_project_id: Annotated[str | None, typer.Option("--source-project", help="Affected/source project")] = None,
    run_ref: Annotated[str | None, typer.Option("--run", help="Run or activity reference, independent of session")] = None,
    role: Annotated[str | None, typer.Option("--role", help="Reporting role")] = None,
    occurred_at: Annotated[str | None, typer.Option("--at", help="Observation time in ISO 8601 with timezone")] = None,
    consequence: Annotated[str | None, typer.Option("--consequence", help="Observed consequence")] = None,
    workaround: Annotated[str | None, typer.Option("--workaround", help="Workaround used")] = None,
    evidence_refs: Annotated[list[str] | None, typer.Option("--evidence-ref", help="Sanitized evidence reference; repeatable")] = None,
) -> None:
    """Report new feedback on a component.

    \b
    Examples:
      st feedback report sf.cli "Error message unhelpful" --type friction --severity medium
      st feedback report ah.memory "Pre-load cross-project context" --type idea
      st feedback report sf.checkpoints "Checkpoint flow worked perfectly" --type praise
      st feedback report sf.check "Cache ruff results for unchanged files" --type improvement
      st feedback report sf.cli "Same failure again" --session sess-123 --vote-if-match
    """
    report_impl(
        component_id,
        title,
        feedback_type=feedback_type,
        severity=severity,
        description=description,
        project_id=project_id,
        session_id=session_id,
        agent_slug=agent_slug,
        model_used=model_used,
        session_type=session_type,
        vote_if_duplicate=vote_if_match,
        occurrence={"occurrence_id": occurrence_id, "source_project_id": source_project_id,
                    "run_ref": run_ref, "role": role, "occurred_at": occurred_at,
                    "consequence": consequence, "workaround": workaround, "evidence_refs": evidence_refs},
    )


@app.command("search")
def search(
    query: Annotated[str | None, typer.Argument(help="Search query")] = None,
    query_option: Annotated[
        str | None,
        typer.Option("--query", "-q", help="Explicit search query; use when the text starts with - or --"),
    ] = None,
    component_id: Annotated[
        str | None, typer.Option("--component", "-c", help="Filter by component")
    ] = None,
    feedback_type: Annotated[
        str | None, typer.Option("--type", "-t", help="Filter by type")
    ] = None,
    status: Annotated[
        str | None, typer.Option("--status", help="Filter by status: active, open, acknowledged, resolved, wont_fix, archived")
    ] = None,
    project_id: Annotated[
        str | None, typer.Option("--project", "-p", help="Filter by project")
    ] = None,
    sort: Annotated[
        str, typer.Option("--sort", help="Sort: votes, newest, oldest")
    ] = "votes",
    limit: Annotated[int, typer.Option("--limit", "-l", help="Max results")] = 20,
) -> None:
    """Search feedback items by keyword.

    \b
    Examples:
      st feedback search "memory injection"
      st feedback search --query "--frontend-only compiler flag"
      st feedback search "error" --component sf.cli --type friction
    """
    if query is not None and query_option is not None:
        raise typer.BadParameter("Specify either SEARCH query or --query, not both")
    resolved_query = query_option if query_option is not None else query
    if resolved_query is None:
        raise typer.BadParameter("Search query is required")
    search_impl(
        resolved_query,
        component_id=component_id,
        feedback_type=feedback_type,
        status=status,
        project_id=project_id,
        sort=sort,
        limit=limit,
    )


@app.command("list")
def list_feedback(
    component_id: Annotated[
        str | None, typer.Option("--component", "-c", help="Filter by component")
    ] = None,
    feedback_type: Annotated[
        str | None, typer.Option("--type", "-t", help="Filter by type")
    ] = None,
    status: Annotated[
        str | None, typer.Option("--status", help="Filter by status: active, open, acknowledged, resolved, wont_fix, archived")
    ] = None,
    project_id: Annotated[
        str | None, typer.Option("--project", "-p", help="Filter by project")
    ] = None,
    sort: Annotated[
        str, typer.Option("--sort", help="Sort: votes, newest, oldest")
    ] = "votes",
    limit: Annotated[int, typer.Option("--limit", "-l", help="Max results")] = 50,
) -> None:
    """List feedback items with filters.

    \b
    Examples:
      st feedback list
      st feedback list --component ah.memory --type idea
      st feedback list --sort votes --status active
    """
    list_impl(
        component_id=component_id,
        feedback_type=feedback_type,
        status=status,
        project_id=project_id,
        sort=sort,
        limit=limit,
    )


@app.command("get")
def get(
    item_id: Annotated[str, typer.Argument(help="Feedback item ID")],
    json_output: Annotated[bool, typer.Option("--json", help="Output raw JSON")] = False,
) -> None:
    """Get full details of a feedback item including votes.

    \b
    Examples:
      st feedback get a1b2c3d4-...
    """
    get_impl(item_id, json_output=json_output)


@app.command("references")
@usage(
    surface="st.feedback.references",
    cmd="st feedback references --run-ref RUN [--run-ref RUN...] [--json]",
    when="reconciling retained feedback for exact known run identities",
    precautions=("read-only; returns at most 200 compact canonical occurrence references",),
    tier="reference",
)
def references(
    run_refs: Annotated[
        list[str], typer.Option("--run-ref", help="Exact retained run identity; repeat for multiple runs")
    ],
    json_output: Annotated[bool, typer.Option("--json", help="Output compact reference JSON")] = False,
) -> None:
    """Read compact canonical feedback references for up to 20 exact runs."""
    references_impl(run_refs, json_output=json_output)


@app.command("vote")
def vote(
    item_id: Annotated[str, typer.Argument(help="Feedback item ID to vote on")],
    session_id: Annotated[
        str | None, typer.Option("--session", help="Session ID casting the vote")
    ] = None,
    comment: Annotated[
        str | None, typer.Option("--comment", "-m", help="Optional comment")
    ] = None,
    agent_slug: Annotated[
        str | None, typer.Option("--agent", help="Agent slug")
    ] = None,
    model_used: Annotated[
        str | None, typer.Option("--model", help="Model used")
    ] = None,
    occurrence_id: Annotated[str | None, typer.Option("--occurrence", help="Stable observation ID; reuse for retries and relays")] = None,
    source_project_id: Annotated[str | None, typer.Option("--source-project", help="Affected/source project")] = None,
    run_ref: Annotated[str | None, typer.Option("--run", help="Run or activity reference, independent of session")] = None,
    role: Annotated[str | None, typer.Option("--role", help="Reporting role")] = None,
    occurred_at: Annotated[str | None, typer.Option("--at", help="Observation time in ISO 8601 with timezone")] = None,
    consequence: Annotated[str | None, typer.Option("--consequence", help="Observed consequence")] = None,
    workaround: Annotated[str | None, typer.Option("--workaround", help="Workaround used")] = None,
    evidence_refs: Annotated[list[str] | None, typer.Option("--evidence-ref", help="Sanitized evidence reference; repeatable")] = None,
) -> None:
    """Vote on an existing feedback item.

    \b
    Examples:
      st feedback vote a1b2c3d4 --session sess-123
      st feedback vote a1b2c3d4 --session sess-123 --comment "Hit this during autocode"
    """
    vote_impl(
        item_id,
        session_id=session_id,
        comment=comment,
        agent_slug=agent_slug,
        model_used=model_used,
        occurrence={"occurrence_id": occurrence_id, "source_project_id": source_project_id,
                    "run_ref": run_ref, "role": role, "occurred_at": occurred_at,
                    "consequence": consequence, "workaround": workaround, "evidence_refs": evidence_refs},
    )


@app.command("resolve")
def resolve(
    item_id: Annotated[str, typer.Argument(help="Feedback item ID to resolve")],
    note: Annotated[
        str | None, typer.Option("--note", "-n", "--message", "-m", help="Resolution note")
    ] = None,
) -> None:
    """Resolve a feedback item.

    \b
    Examples:
      st feedback resolve a1b2c3d4 --note "Fixed in commit abc123"
      st feedback resolve a1b2c3d4 -m "Fixed in commit abc123"
    """
    resolve_impl(item_id, note=note)


@app.command("archive")
def archive(
    item_id: Annotated[str, typer.Argument(help="Feedback item ID to archive")],
    note: Annotated[
        str | None, typer.Option("--note", "-n", help="Archive note")
    ] = None,
) -> None:
    """Archive a resolved or won't-fix feedback item."""
    archive_impl(item_id, note=note)


@app.command("merge")
def merge(
    item_id: Annotated[str, typer.Argument(help="Duplicate feedback item ID to merge")],
    target_item_id: Annotated[str, typer.Argument(help="Canonical feedback item ID")],
) -> None:
    """Merge a duplicate feedback item into a canonical feedback item."""
    merge_impl(item_id, target_item_id)


@app.command("delete")
def delete(
    item_id: Annotated[str, typer.Argument(help="Feedback item ID to delete")],
) -> None:
    """Delete a feedback item and all its votes.

    \b
    Examples:
      st feedback delete a1b2c3d4-...
    """
    delete_impl(item_id)


@app.command("summary")
def summary(
    project_id: Annotated[
        str | None, typer.Option("--project", "-p", help="Filter by project")
    ] = None,
    days: Annotated[int, typer.Option("--days", help="Lookback window in days")] = 30,
) -> None:
    """Get aggregated feedback summary.

    \b
    Examples:
      st feedback summary
      st feedback summary --project summitflow --days 7
    """
    summary_impl(project_id=project_id, days=days)


@app.command("link")
def link(
    item_id: Annotated[str, typer.Argument(help="Reviewed feedback item")],
    task_id: Annotated[str, typer.Argument(help="Existing task chosen by the orchestrator")],
) -> None:
    """Link reviewed feedback to an existing ordinary task; never create or approve it."""
    link_impl(item_id, task_id)
