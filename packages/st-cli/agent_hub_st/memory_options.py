"""Common Typer option definitions for memory commands."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

# Scope options
WriteScopeOpt = Annotated[
    str | None,
    typer.Option("--scope", "-s", help="Explicit memory scope: global, project, or agent; omitted on update preserves scope"),
]

ScopeOpt = Annotated[
    str,
    typer.Option("--scope", "-s", help="Memory scope (global or project)"),
]

ScopeIdOpt = Annotated[
    str | None,
    typer.Option("--scope-id", help="Scope identifier (e.g., project ID)"),
]

# Tier options
TierOpt = Annotated[
    str,
    typer.Option("--tier", "-t", help="Injection tier (mandate, guardrail, reference)"),
]

TierFilterOpt = Annotated[
    str | None,
    typer.Option("--tier", "-t", help="Filter by tier (mandate, guardrail, reference)"),
]

TierUpdateOpt = Annotated[
    str | None,
    typer.Option("--tier", "-t", help="New tier (mandate/guardrail/reference)"),
]

# Content and metadata options
ContentArg = Annotated[str | None, typer.Argument(help="Learning content to save")]

ContentOpt = Annotated[
    str | None,
    typer.Option("--content", "-c", help="New content for the episode"),
]

ContentFileOpt = Annotated[
    str | None,
    typer.Option(
        "--content-file",
        help="Read content from a file path or '-' for stdin",
    ),
]

SummaryOpt = Annotated[
    str,
    typer.Option(
        "--summary", "-S", help="Action phrase for TOON index (10-40 chars)"
    ),
]

SaveSummaryOpt = Annotated[
    str | None,
    typer.Option("--summary", "-S", help="Action phrase for TOON index (10-40 chars)"),
]

# Format command options
FormatTopicOpt = Annotated[str, typer.Option("--topic", help="Required compact topic header, without markdown or colon")]
FormatInstructionOpt = Annotated[str, typer.Option("--instruction", help="Required primary instruction sentence")]
FormatProhibitionOpt = Annotated[str | None, typer.Option("--prohibition", help="Optional second sentence for a direct prohibition")]
FormatWhyOpt = Annotated[str | None, typer.Option("--why", help="Optional brief rationale; emitted as 'Why: ...'")]
FormatSummaryOpt = Annotated[str | None, typer.Option("--summary", "-S", help="Optional summary override (default: suggested from instruction)")]

SummaryUpdateOpt = Annotated[
    str | None,
    typer.Option("--summary", "-S", help="Update summary (10-40 chars for TOON index)"),
]

ConfidenceOpt = Annotated[
    int,
    typer.Option("--confidence", "-c", help="Confidence level 0-100"),
]

ContextOpt = Annotated[
    str | None,
    typer.Option("--context", help="Optional context about the learning source"),
]

ChangeReasonOpt = Annotated[
    str | None,
    typer.Option("--change-reason", help="Optional reason recorded in memory revision history"),
]

PinnedOpt = Annotated[
    bool,
    typer.Option("--pinned", "-p", help="Pin episode (always inject regardless of budget)"),
]

PinnedUpdateOpt = Annotated[
    bool | None,
    typer.Option(
        "--pinned/--no-pinned", help="Pin episode (always inject regardless of budget)"
    ),
]

TriggerTypesOpt = Annotated[
    str | None,
    typer.Option(
        "--trigger-types", "-T", help="Comma-separated task types (e.g., database,memory)"
    ),
]

TriggerTypesUpdateOpt = Annotated[
    str | None,
    typer.Option(
        "--trigger-types", help="Comma-separated task types (backend,frontend,database,etc.)"
    ),
]

TriggerPhasesOpt = Annotated[
    str | None,
    typer.Option(
        "--trigger-phases",
        help="Comma-separated subtask phases (implementation,verification,cleanup,etc.)",
    ),
]

TriggerPhasesUpdateOpt = Annotated[
    str | None,
    typer.Option(
        "--trigger-phases",
        help="Comma-separated subtask phases (implementation,verification,cleanup,etc.)",
    ),
]

ContextKindOpt = Annotated[
    str | None,
    typer.Option(
        "--context-kind",
        help="Semantic context channel (policy, reference, capability, continuity, signal)",
    ),
]

ContextKindUpdateOpt = Annotated[
    str | None,
    typer.Option(
        "--context-kind",
        help="Semantic context channel (policy, reference, capability, continuity, signal)",
    ),
]

RenderModeOpt = Annotated[
    str | None,
    typer.Option(
        "--render-mode",
        help=(
            "Per-memory render expansion: full | compact | summary. "
            "Forces L2 / L1 / L0 rendering across all consumer profiles."
        ),
    ),
]

RenderModeUpdateOpt = Annotated[
    str | None,
    typer.Option(
        "--render-mode",
        help=(
            "Per-memory render expansion: full | compact | summary. "
            "Pass 'auto' (or 'clear') to revert to profile-driven tiering. "
            "Omit to leave unchanged."
        ),
    ),
]

ConsumerProfilesOpt = Annotated[
    str | None,
    typer.Option("--consumer-profiles", help="Comma-separated consumer profiles to target"),
]

ExcludeConsumerProfilesOpt = Annotated[
    str | None,
    typer.Option(
        "--exclude-consumer-profiles",
        help="Comma-separated consumer profiles to exclude",
    ),
]

AgentSlugsOpt = Annotated[
    str | None,
    typer.Option("--agent-slugs", help="Comma-separated agent slugs to target"),
]

ExcludeAgentSlugsOpt = Annotated[
    str | None,
    typer.Option("--exclude-agent-slugs", help="Comma-separated agent slugs to exclude"),
]

AudienceTagsOpt = Annotated[
    str | None,
    typer.Option("--audience-tags", help="Comma-separated audience tags to target"),
]

ExcludeAudienceTagsOpt = Annotated[
    str | None,
    typer.Option("--exclude-audience-tags", help="Comma-separated audience tags to exclude"),
]

ClearApplicabilityOpt = Annotated[
    bool,
    typer.Option("--clear-applicability", help="Remove all applicability targeting/exclusions"),
]

TagsOpt = Annotated[
    str | None,
    typer.Option(
        "--tags",
        help="Comma-separated memory tags (e.g., finance-relevant,portfolio)",
    ),
]

TagsUpdateOpt = Annotated[
    str | None,
    typer.Option(
        "--tags",
        help="Replace episode tags with a comma-separated list",
    ),
]

ClearTagsOpt = Annotated[
    bool,
    typer.Option(
        "--clear-tags",
        help="Remove all tags from the episode",
    ),
]

# Query and search options
QueryArg = Annotated[str, typer.Argument(help="Search query")]

LimitOpt = Annotated[
    int,
    typer.Option("--limit", "-l", help="Max episodes to return (1-300)"),
]

SearchLimitOpt = Annotated[
    int,
    typer.Option("--limit", "-l", help="Max results (1-300)"),
]

MinScoreOpt = Annotated[
    float,
    typer.Option("--min-score", help="Minimum relevance score (0.0-1.0)"),
]

CursorOpt = Annotated[
    str | None,
    typer.Option("--cursor", help="Pagination cursor from previous response"),
]

# UUID options
UUIDsArg = Annotated[list[str], typer.Argument(help="Episode UUID(s) to retrieve")]
UUIDsDeleteArg = Annotated[list[str], typer.Argument(help="Episode UUID(s) to delete")]
UUIDArg = Annotated[str, typer.Argument(help="Episode UUID (full or 8-char prefix)")]
RevisionArg = Annotated[str, typer.Argument(help="Revision UUID to restore to")]
UUIDsOptArg = Annotated[
    list[str] | None,
    typer.Argument(help="Specific UUIDs to export (optional)"),
]
UUIDsBatchArg = Annotated[
    list[str] | None,
    typer.Argument(help="UUIDs to update (when using --tier)"),
]

HistoryLimitOpt = Annotated[
    int,
    typer.Option("--limit", "-l", help="Max revisions to return (1-100)"),
]

# Batch operation options
InputFileOpt = Annotated[
    Path | None,
    typer.Option("--file", "-f", help="JSON file with updates [{uuid, tier}]"),
]

JsonInputOpt = Annotated[
    str | None,
    typer.Option("--json", "-j", help="JSON string with updates"),
]

BatchTierOpt = Annotated[
    str | None,
    typer.Option("--tier", "-t", help="Tier to apply to all UUIDs"),
]

# Import/export options
OutputOpt = Annotated[
    Path | None,
    typer.Option(
        "--output",
        "-o",
        help="Output file or directory (no extension = directory with tier-split files)",
    ),
]

FullExportOpt = Annotated[
    bool,
    typer.Option(
        "--full", "-f", help="Export all fields (default: minimal fields for tune_it)"
    ),
]

InputPathArg = Annotated[
    Path,
    typer.Argument(help="JSON file or directory to import (from st memory export)"),
]

DryRunOpt = Annotated[
    bool,
    typer.Option("--dry-run", help="Show what would change without applying"),
]

# Cleanup options
OrphanedOpt = Annotated[
    bool,
    typer.Option("--orphaned", help="Clean up orphaned edges (stale episode refs)"),
]

StaleOpt = Annotated[
    bool,
    typer.Option("--stale", help="Clean up stale memories not accessed within TTL"),
]

TtlDaysOpt = Annotated[
    int,
    typer.Option("--ttl-days", help="TTL in days for stale cleanup (default 30)"),
]
