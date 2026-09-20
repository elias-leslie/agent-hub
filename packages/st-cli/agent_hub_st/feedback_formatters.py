"""TOON output formatters for feedback commands."""

from __future__ import annotations

import sys
from typing import Any


def format_item_line(item: dict[str, Any]) -> str:
    """Format a single feedback item as a TOON line.

    Format: id_short|status|type|component|N votes|title
    """
    id_short = item.get("id", "")[:8]
    status = item.get("status", "open")
    ftype = item.get("feedback_type", "?")
    component = item.get("component_id", "?")
    votes = item.get("vote_count", 1)
    title = item.get("title", "")
    severity = item.get("severity")
    severity_tag = f"[{severity}] " if severity else ""
    return f"{id_short}|{status}|{ftype}|{component}|{votes} votes|{severity_tag}{title}"


def output_feedback_list(items: list[dict[str, Any]], total: int) -> None:
    """Output feedback list in TOON format."""
    open_count = sum(1 for i in items if i.get("status") in ("open", "acknowledged"))
    resolved_count = sum(1 for i in items if i.get("status") == "resolved")
    print(f"FEEDBACK[{total}]:open={open_count}|resolved={resolved_count}")
    for item in items:
        print(format_item_line(item))


def output_feedback_created(item: dict[str, Any]) -> None:
    """Output for newly created feedback item."""
    id_short = item.get("id", "")[:8]
    ftype = item.get("feedback_type", "?")
    component = item.get("component_id", "?")
    title = item.get("title", "")
    print(f"FEEDBACK:CREATED:{id_short}|{ftype}|{component}|{title}")


def output_feedback_deduped(item: dict[str, Any]) -> None:
    """Output when a report was converted into a vote on an existing item."""
    id_short = item.get("id", "")[:8]
    component = item.get("component_id", "?")
    ftype = item.get("feedback_type", "?")
    votes = item.get("vote_count", 1)
    title = item.get("title", "")
    print(f"FEEDBACK:VOTED_EXISTING:{id_short}|{component}|{ftype}|votes={votes}|{title}")


def output_feedback_existing(item: dict[str, Any]) -> None:
    """Output when a duplicate already existed and no new vote was recorded."""
    id_short = item.get("id", "")[:8]
    component = item.get("component_id", "?")
    ftype = item.get("feedback_type", "?")
    votes = item.get("vote_count", 1)
    title = item.get("title", "")
    print(f"FEEDBACK:EXISTS:{id_short}|{component}|{ftype}|votes={votes}|{title}")


def output_feedback_voted(item: dict[str, Any]) -> None:
    """Output for a vote on an existing item."""
    id_short = item.get("id", "")[:8]
    component = item.get("component_id", "?")
    ftype = item.get("feedback_type", "?")
    votes = item.get("vote_count", 1)
    title = item.get("title", "")
    print(f"VOTE:{id_short}|{component}|{ftype}|votes={votes}|{title}")


def output_feedback_detail(item: dict[str, Any]) -> None:
    """Output detailed view of a feedback item."""
    print(f"ID: {item.get('id', '?')}")
    print(f"Type: {item.get('feedback_type', '?')}")
    print(f"Component: {item.get('component_id', '?')}")
    print(f"Status: {item.get('status', '?')}")
    print(f"Title: {item.get('title', '?')}")
    if item.get("description"):
        print(f"Description: {item['description']}")
    if item.get("severity"):
        print(f"Severity: {item['severity']}")
    print(f"Votes: {item.get('vote_count', 1)}")
    if item.get("linked_task_id"):
        print(f"Linked Task: {item['linked_task_id']}")
    if item.get("resolution_note"):
        print(f"Resolution: {item['resolution_note']}")
    print(f"Created: {item.get('created_at', '?')}")

    votes = item.get("votes", [])
    if votes:
        print(f"\nVotes ({len(votes)}):")
        for vote in votes:
            agent = vote.get("agent_slug", "unknown")
            comment = vote.get("comment", "")
            comment_str = f" — {comment}" if comment else ""
            print(f"  {vote.get('session_id', '?')[:8]} ({agent}){comment_str}")


def output_duplicate_candidates(candidates: list[dict[str, Any]]) -> None:
    """Output duplicate candidates as informational TOON lines."""
    print("FEEDBACK:DUPLICATES_FOUND", file=sys.stderr)
    for c in candidates:
        id_short = c.get("id", "")[:8]
        ftype = c.get("feedback_type", "?")
        component = c.get("component_id", "?")
        votes = c.get("vote_count", 1)
        title = c.get("title", "")
        print(
            f"  #{id_short} [{ftype}] {component}: \"{title}\" ({votes} votes)",
            file=sys.stderr,
        )
    print(
        "  Use: st feedback report ... --session <session-id> --vote-if-match",
        file=sys.stderr,
    )


def output_summary(summary: dict[str, Any]) -> None:
    """Output feedback summary in TOON format."""
    total = summary.get("total_items", 0)
    print(f"FEEDBACK_SUMMARY:total={total}")

    by_component = summary.get("by_component", [])
    if by_component:
        print("\nBy Component:")
        for c in by_component:
            cid = c.get("component_id", "?")
            open_count = c.get("open_count", 0)
            resolved = c.get("resolved_count", 0)
            friction = c.get("friction_count", 0)
            ideas = c.get("idea_count", 0)
            print(f"  {cid}: open={open_count} resolved={resolved} friction={friction} ideas={ideas}")

    top = summary.get("top_unresolved", [])
    if top:
        print("\nTop Unresolved:")
        for item in top[:5]:
            id_short = str(item.get("id", ""))[:8]
            votes = item.get("vote_count", 1)
            title = item.get("title", "")
            print(f"  #{id_short} ({votes} votes) {title}")
