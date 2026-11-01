"""st ctx changes | show | keep | refuse | rework: the after-the-fact review of agent context changes.

Agents keep writing memories and prompts with no gate; this queue is read afterwards. A decision names the revision the
reviewer saw (``through_revision``), so a target that changed since returns 409 and nothing is changed. Writes go through
``agent_hub_request``, which sends X-Context-Writer, so each decision names the deciding session.
"""

from __future__ import annotations

import difflib
import os
from pathlib import Path
from typing import Annotated, Any

import typer
from st_sdk.output import output_error, output_json
from st_sdk.usage import usage

from ._api_paths import CONTEXT_CHANGES_PATH, CONTEXT_DECISIONS_PATH, CONTEXT_KEEP_PATH, CONTEXT_REFUSE_PATH, CONTEXT_REWORK_PATH
from .ctx_format import ON_DEMAND, TASKS, TOOL, UNKNOWN, age, emit, obj, rows, short, tok, when
from .memory_api import agent_hub_request

AsJson = Annotated[bool, typer.Option("--json", help="Print the API response as JSON.")]
Ids = Annotated[list[str] | None, typer.Argument(help="Row id from st ctx changes (a unique prefix of it works)")]
Session = Annotated[str | None, typer.Option("--session", help="Every unreviewed row this writer session touched.")]
Note = Annotated[str | None, typer.Option("--note", help="Why, kept with the decision.")]
OWNER_ASK = "Only when the owner asked for it in this session."


def _queue(session: str | None = None, kind: str | None = None) -> dict[str, Any]:
    params = {key: value for key, value in (("session", session), ("kind", kind)) if value}
    return obj(agent_hub_request("GET", CONTEXT_CHANGES_PATH, params=params or None, tool_name=TOOL))


def _row_id(row: dict[str, Any]) -> str:
    return f"{row.get('target_kind')}:{str(row.get('target_id'))[:8]}"


def _writer(row: dict[str, Any]) -> str:
    for writer in rows(row.get("writers")):
        who = writer.get("session") or (f"delivery:{writer['delivery'][:8]}" if writer.get("delivery") else None)
        if who or writer.get("kind"):
            what = "/".join(str(x) for x in (writer.get("harness"), writer.get("work_role")) if x)
            return f"{short(who or writer.get('kind'), 18)}{' ' + what if what else ''}"
    return UNKNOWN


def _reach(row: dict[str, Any]) -> str:
    if row.get("tokens_per_day") is None:
        return "reach ?"
    return f"{tok(row.get('delta_tokens'), sign=True)}t x{obj(row.get('reach')).get('starts_per_day', 0):g}/d"


def _find(queue: dict[str, Any], wanted: str) -> dict[str, Any]:
    """One row by full key, ``kind:id`` prefix, or a bare target-id prefix (at least 4 characters)."""
    needle = wanted.lower()
    hits = []
    for row in rows(queue.get("rows")):
        key, target = str(row.get("key") or "").lower(), str(row.get("target_id") or "").lower()
        short_id = _row_id(row).lower()
        if needle in (key, target, short_id) or (len(needle) >= 4 and (key.startswith(needle) or target.startswith(needle))):
            hits.append(row)
    if len(hits) != 1:
        output_error(f"{len(hits)} unreviewed changes match {wanted!r}; list them with st ctx changes" if hits
                     else f"No unreviewed change matches {wanted!r}; list them with st ctx changes")
        raise typer.Exit(1)
    return hits[0]


def _item(row: dict[str, Any]) -> dict[str, Any]:
    item = {"target_kind": row.get("target_kind"), "target_id": row.get("target_id"), "through_revision": row.get("through_revision")}
    if row.get("version") is not None:
        item["expected_version"] = row["version"]
    return item


def _selected(ids: list[str] | None, session: str | None) -> list[dict[str, Any]]:
    if not ids and not session:
        output_error("Name a change (st ctx changes) or --session")
        raise typer.Exit(2)
    queue = _queue(session=session)
    chosen = [_find(queue, wanted) for wanted in ids or []] if ids else rows(queue.get("rows"))
    if not chosen:
        output_error(f"No unreviewed changes from session {session}")
        raise typer.Exit(1)
    return chosen


def _result_lines(verb: str, response: dict[str, Any]) -> list[str]:
    results = rows(response.get("results"))
    lines = [f"{verb} {len(results)} change{'s' if len(results) != 1 else ''}"]
    for result in results[:9]:
        undid = len(rows(result.get("also_undid")))
        lines.append(f"  {str(result.get('key'))[:24]} {result.get('outcome')}" + (f" (also undid {undid} later write{'s' if undid != 1 else ''})" if undid else ""))
    if len(results) > 9:
        lines.append(f"  +{len(results) - 9} more")
    linked = [str(key) for key in response.get("linked_pending") or []]
    if linked:
        lines.append(f"  {len(linked)} more unreviewed from the same sessions: {', '.join(short(k, 22) for k in linked[:2])}")
    return lines


def _decide(path: str, verb: str, chosen: list[dict[str, Any]], note: str | None, as_json: bool) -> None:
    response = obj(agent_hub_request("POST", path, json={"items": [_item(r) for r in chosen], **({"note": note} if note else {})}, tool_name=TOOL))
    if as_json:
        output_json(response)
        return
    emit(_result_lines(verb, response))


def _narrow(spec: str) -> dict[str, str]:
    kind, _, value = spec.partition(":")
    if kind == "session" and not value:
        return {"to": "session"}
    if kind == "project" and value:
        return {"to": "project", "project_id": value}
    if kind == "role" and value:
        return {"to": "role", "role": value}
    raise typer.BadParameter("use project:ID, role:ROLE or session", param_hint="--narrow")


def register(app: typer.Typer) -> None:
    @app.command("changes")
    @usage(surface="st.ctx.changes", cmd="st ctx changes [--session S | --mine] [--kind memory|prompt|placement] [--decided]",
           when="unreviewed agent edits to memories, prompts and placements, with reach and writer session; --decided lists past keeps, reworks and refusals",
           task_types=TASKS, on_demand=ON_DEMAND)
    def changes(
        session: Session = None,
        mine: Annotated[bool, typer.Option("--mine", help="Only rows this session (AICO_SESSION_ID) wrote.")] = False,
        kind: Annotated[str | None, typer.Option("--kind", help="memory, prompt or placement")] = None,
        decided: Annotated[bool, typer.Option("--decided", help="Past decisions instead of the queue.")] = False,
        limit: Annotated[int, typer.Option("--limit", min=1, max=11)] = 9,
        as_json: AsJson = False,
    ) -> None:
        """The review queue, newest first."""
        if mine:
            session = os.environ.get("AICO_SESSION_ID", "").strip() or None
            if not session:
                output_error("AICO_SESSION_ID is not set; pass --session")
                raise typer.Exit(2)
        if decided:
            params = {"limit": limit, **({"target_kind": kind} if kind else {})}
            past = rows(agent_hub_request("GET", CONTEXT_DECISIONS_PATH, params=params, tool_name=TOOL))
            if as_json:
                output_json(past)
                return
            emit([f"DECIDED newest {len(past)}", *(f"  {age(r.get('created_at')):>3} {r.get('decision')} {r.get('target_kind')}:{str(r.get('target_id'))[:8]}"
                                                    f" by {short(r.get('by'), 18)}{' - ' + short(r.get('note'), 30) if r.get('note') else ''}" for r in past)])
            return
        queue = _queue(session=session, kind=kind)
        if as_json:
            output_json(queue)
            return
        summary, queued = obj(queue.get("summary")), rows(queue.get("rows"))
        unknown = f", reach unknown {summary.get('unknown_reach')}" if summary.get("unknown_reach") else ""
        lines = [f"CHANGES {summary.get('count', len(queued))} unreviewed ({summary.get('global_count', 0)} global) "
                 f"{tok(summary.get('tokens_per_day'), sign=True)} tok/day{unknown}"]
        for row in queued[:limit]:
            hint = obj(row.get("hint"))
            lines.append(f"  {_row_id(row)} {row.get('change')} {row.get('scope_after')} {short(row.get('title'), 30)!r} {_reach(row)} "
                         f"{_writer(row)} {age(row.get('last_at'))}" + (f" [{short(hint.get('label'), 16)}]" if hint.get("label") else ""))
        if len(queued) > limit:
            lines.append(f"  +{len(queued) - limit} more (--kind, --session narrow)")
        automatic = len(rows(queue.get("automatic")))
        if automatic:
            lines.append(f"  {automatic} system writes this week, not queued")
        emit(lines)

    @app.command("show")
    @usage(surface="st.ctx.show", cmd="st ctx show ID", when="one queued change: what changed, who wrote it, who receives it, the diff",
           task_types=TASKS, on_demand=ON_DEMAND)
    def show(id_: Annotated[str, typer.Argument(metavar="ID", help="Row id from st ctx changes")], as_json: AsJson = False) -> None:
        """One queue row with its diff."""
        row = _find(_queue(), id_)
        if as_json:
            output_json(row)
            return
        reach = obj(row.get("reach"))
        receivers = ", ".join(f"{r.get('harness')}/{r.get('role') or '*'}" for r in rows(reach.get("receivers"))[:4])
        lines = [f"{row.get('key')} {row.get('change')} {short(row.get('title'), 40)!r} {row.get('scope_before') or UNKNOWN}->{row.get('scope_after')} "
                 f"{when(row.get('first_at'))}..{when(row.get('last_at'))}",
                 f"  by {_writer(row)}; {_reach(row)}; reaches {receivers or UNKNOWN} ({reach.get('starts', 0)} starts, {reach.get('subagent_starts', 0)} subagent)",
                 f"  revision {str(row.get('through_revision'))[:8]} version {row.get('version')}; linked {len(row.get('linked') or [])}"
                 + (f"; undoing it also undoes {len(rows(row.get('also_undoes')))} later owner/system writes" if row.get("also_undoes") else "")]
        hint = obj(row.get("hint"))
        if hint.get("label"):
            lines.append(f"  review agent: {hint.get('label')} {hint.get('decision') or ''} {short(hint.get('reason'), 80)}")
        lines += _diff_lines(obj(row.get("before")), obj(row.get("after")), room=15 - len(lines))
        emit(lines)

    @app.command("keep")
    @usage(surface="st.ctx.keep", cmd="st ctx keep ID... | --session S [--note TEXT]",
           when="record a change as reviewed and fine; nothing else changes. " + OWNER_ASK, task_types=TASKS, on_demand=ON_DEMAND)
    def keep(ids: Ids = None, session: Session = None, note: Note = None, as_json: AsJson = False) -> None:
        """Mark changes reviewed and acceptable."""
        _decide(CONTEXT_KEEP_PATH, "kept", _selected(ids, session), note, as_json)

    @app.command("refuse")
    @usage(surface="st.ctx.refuse", cmd="st ctx refuse ID... | --session S [--note TEXT]",
           when="undo changes, all or nothing: a create is archived, an update or delete restored (409 if it changed since). " + OWNER_ASK,
           task_types=TASKS, on_demand=ON_DEMAND)
    def refuse(ids: Ids = None, session: Session = None, note: Note = None, as_json: AsJson = False) -> None:
        """Undo changes."""
        _decide(CONTEXT_REFUSE_PATH, "refused", _selected(ids, session), note, as_json)

    @app.command("rework")
    @usage(surface="st.ctx.rework", cmd="st ctx rework ID (-f FILE | --summary S | --name N | --narrow project:ID|role:R|session)",
           when="edit a change in place or narrow who gets it (session = archive); a memory or prompt, not a placement. " + OWNER_ASK,
           task_types=TASKS, on_demand=ON_DEMAND)
    def rework(
        id_: Annotated[str, typer.Argument(metavar="ID", help="Row id from st ctx changes")],
        file: Annotated[Path | None, typer.Option("-f", "--file", help="New content from this file.", exists=True, dir_okay=False)] = None,
        summary: Annotated[str | None, typer.Option("--summary")] = None,
        name: Annotated[str | None, typer.Option("--name")] = None,
        narrow: Annotated[str | None, typer.Option("--narrow", help="project:ID, role:ROLE or session")] = None,
        note: Note = None,
        as_json: AsJson = False,
    ) -> None:
        """Edit or narrow one change."""
        edit = {key: value for key, value in (("content", file.read_text(encoding="utf-8") if file else None), ("summary", summary), ("name", name)) if value}
        if bool(edit) == bool(narrow):
            raise typer.BadParameter("give an edit (-f, --summary, --name) or --narrow, not both or neither")
        row = _find(_queue(), id_)
        body = {**_item(row), **({"edit": edit} if edit else {"narrow": _narrow(narrow or "")}), **({"note": note} if note else {})}
        response = obj(agent_hub_request("POST", CONTEXT_REWORK_PATH, json=body, tool_name=TOOL))
        if as_json:
            output_json(response)
            return
        emit(_result_lines("reworked", response))


def _diff_lines(before: dict[str, Any], after: dict[str, Any], *, room: int) -> list[str]:
    """Changed fields: content as a unified diff, short fields as old -> new, within ``room`` lines."""
    out: list[str] = []
    for key in sorted(set(before) | set(after)):
        old, new = before.get(key), after.get(key)
        if old == new or key == "content":
            continue
        out.append(f"  {key}: {short(old, 40)} -> {short(new, 40)}")
    if before.get("content") != after.get("content"):
        diff = [line for line in difflib.unified_diff(str(before.get("content") or "").splitlines(), str(after.get("content") or "").splitlines(), lineterm="", n=0)
                if not line.startswith(("---", "+++", "@@"))]
        out += [f"  {short(line, 110)}" for line in diff]
    if len(out) > room:
        out = [*out[: max(room - 1, 0)], f"  … {len(out) - max(room - 1, 0)} more changed lines (--json)"]
    return out
