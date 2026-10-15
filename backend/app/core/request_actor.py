"""Who made the current API request, for revision attribution.

The access-control middleware binds the caller (client id and request source,
or the internal secret) for each request. Revision writers call ``attribute`` so
prompt, agent and memory history name the calling client instead of a bare
``api``. Outside a request (workers, CLI) labels pass through unchanged.
"""

from __future__ import annotations

from contextvars import ContextVar

_MAX_LABEL = 100  # changed_by columns are String(100)
_actor: ContextVar[str | None] = ContextVar("agent_hub_request_actor", default=None)


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
