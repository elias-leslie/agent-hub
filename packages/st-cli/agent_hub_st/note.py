"""`st note` — quick alias of `st memory save`, tagged `#kind:note`.

Wraps free text as a standard memory episode (`**Note**: <text>`) at reference
tier and saves it with the reserved `#kind:note` tag, so notes are searchable
alongside other learnings and filterable by tag. Notes follow the same
FORMAT_STANDARD as `st memory save` (it is the underlying call). Compactness
enforcement is skipped — notes are jottings, not terse policy.
"""

from __future__ import annotations

from typing import Annotated

import typer
from st_sdk.usage import usage
from st_sdk.context import OutputContext

from .memory_crud import save_impl
from .memory_validation import build_episode_content, suggest_summary

_NOTE_TAG = "#kind:note"


@usage(surface="st.note", cmd="st note <text> --scope project --scope-id <project>", when="save a scoped note in Agent Hub memory",
       task_types=("memory-admin",), on_demand="memory authoring")
def note(
    ctx: typer.Context,
    text: Annotated[str, typer.Argument(help="Note text")],
    topic: Annotated[str, typer.Option("--topic", help="Episode topic header")] = "Note",
    summary: Annotated[str | None, typer.Option("--summary", "-s", help="Override summary (10-40 chars)")] = None,
    tags: Annotated[str | None, typer.Option("--tags", help="Extra comma-separated tags")] = None,
    scope: Annotated[str, typer.Option("--scope", help="Memory scope")] = "global",
    scope_id: Annotated[str | None, typer.Option("--scope-id", help="Scope id (for project scope)")] = None,
) -> None:
    """Save a quick note to memory, tagged #kind:note.

    Examples: st note "Check the deploy after merge" | st note "..." --tags "#widget:claude-code"
    """
    out = ctx.obj if isinstance(ctx.obj, OutputContext) else OutputContext()
    content = build_episode_content(topic, text)
    resolved_summary = (summary.strip() if summary else suggest_summary(text)) or topic
    merged_tags = _NOTE_TAG if not tags else f"{_NOTE_TAG},{tags}"
    # save_impl validates FORMAT_STANDARD before issuing the API call.
    save_impl(
        out, content, resolved_summary, "reference", 80, None, False,
        None, None, None, None, None, None, None, None, None,
        merged_tags, scope, scope_id,
    )
