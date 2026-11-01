"""Who made the current API request, for revision attribution.

The access-control middleware binds the caller (client id and request source,
or the internal secret) for each request. Revision writers call ``attribute`` so
prompt, agent and memory history name the calling client instead of a bare
``api``. Outside a request (workers, CLI) labels pass through unchanged.

The middleware also binds the request's writer: which agent session made a
change. Agents send ``X-Context-Writer: delivery=<hash>; session=<id>`` (their
context delivery hash and Aico session); the server resolves harness, role and
project from the delivery when reading. Subagents inherit their parent's
environment, so their writes show as the parent session. Owner writes (the
owner token, or the dashboard) are kind ``owner``; other callers are
``client``; writes outside a request are ``system``.
"""

from __future__ import annotations

import re
from contextvars import ContextVar
from dataclasses import dataclass

_MAX_LABEL = 100  # changed_by columns are String(100)
_actor: ContextVar[str | None] = ContextVar("agent_hub_request_actor", default=None)

WRITER_CONTEXT_HEADER = "X-Context-Writer"
_MAX_WRITER_VALUE = 128  # writer_delivery / writer_session columns are String(128)
_WRITER_VALUE = re.compile(r"[^A-Za-z0-9._:@-]")


@dataclass(frozen=True)
class RequestWriter:
    """Who made a change: ``kind`` is owner, agent, client or system."""

    kind: str
    delivery: str | None = None
    session: str | None = None


_SYSTEM_WRITER = RequestWriter(kind="system")
_writer: ContextVar[RequestWriter | None] = ContextVar("agent_hub_request_writer", default=None)


def _clean_writer_value(value: str | None) -> str | None:
    cleaned = _WRITER_VALUE.sub("", (value or "").strip())[:_MAX_WRITER_VALUE]
    return cleaned or None


def parse_writer_header(value: str | None) -> tuple[str | None, str | None]:
    """``(delivery, session)`` from ``delivery=<hash>; session=<id>``; unknown parts are ignored."""
    parts: dict[str, str] = {}
    for item in (value or "").split(";"):
        key, sep, raw = item.partition("=")
        if sep:
            parts[key.strip().lower()] = raw
    return _clean_writer_value(parts.get("delivery")), _clean_writer_value(parts.get("session"))


def classify_request_writer(
    *, writer_header: str | None, owner: bool, dashboard: bool
) -> RequestWriter:
    """Owner for the owner token or the dashboard, agent when a session says who it is, else client."""
    delivery, session = parse_writer_header(writer_header)
    if owner or (dashboard and not (delivery or session)):
        return RequestWriter(kind="owner", delivery=delivery, session=session)
    if delivery or session:
        return RequestWriter(kind="agent", delivery=delivery, session=session)
    return RequestWriter(kind="client")


def bind_request_writer(writer: RequestWriter | None) -> None:
    _writer.set(writer)


def current_request_writer() -> RequestWriter:
    """The bound request writer, or ``system`` outside a request."""
    return _writer.get() or _SYSTEM_WRITER


def writer_columns() -> dict[str, str | None]:
    """Revision columns naming the current writer."""
    writer = current_request_writer()
    return {"writer_kind": writer.kind, "writer_delivery": writer.delivery, "writer_session": writer.session}


def bind_request_actor(*, client_id: str | None, request_source: str | None, internal: bool) -> None:
    kind = "internal" if internal else "client"
    _actor.set(f"{kind}:{client_id or '-'}/{request_source or '-'}"[:_MAX_LABEL])


def current_request_actor() -> str | None:
    return _actor.get()


def attribute(changed_by: str | None) -> str | None:
    """``changed_by`` with the calling client added (alone when the label is just ``api``)."""
    actor = _actor.get()
    if actor is None:
        return changed_by
    if not changed_by or changed_by == "api":
        return actor
    if actor in changed_by:
        return changed_by
    return f"{changed_by} via {actor}"[:_MAX_LABEL]
