"""Normalize OpenCode v2 public session exports; no credential or inference access."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session
from app.services.runtime_context import (
    CanonicalContextDeliveryRequest,
    _resolve_canonical_project_id,
)

from .models import (
    AppendNormalizedEventsRequest,
    NormalizedEvent,
    SessionHeartbeatRequest,
    SessionUpsertRequest,
)
from .service import append_normalized_events, heartbeat_session, upsert_session


class NativeModel(BaseModel):
    providerID: str = Field(min_length=1, max_length=100)
    id: str = Field(min_length=1, max_length=200)

    @property
    def label(self) -> str:
        return f"{self.providerID}/{self.id}"


class NativeLocation(BaseModel):
    directory: str = Field(min_length=1, max_length=4096)


class NativeInfo(BaseModel):
    id: str = Field(pattern=r"^ses_[A-Za-z0-9_-]{1,100}$")
    model: NativeModel
    location: NativeLocation
    parentID: str | None = None
    outcome: Literal["succeeded", "failed", "interrupted"] | None = None


class NativeMessage(BaseModel):
    id: str = Field(pattern=r"^msg_[A-Za-z0-9_-]{1,100}$")
    type: str
    time: dict[str, float] = Field(default_factory=dict)
    model: NativeModel | None = None
    text: str | None = None
    content: list[dict[str, Any]] = Field(default_factory=list)
    error: dict[str, Any] | None = None
    tokens: dict[str, Any] | None = None
    cost: float | None = Field(default=None, ge=0)


class NativeExport(BaseModel):
    info: NativeInfo
    messages: list[NativeMessage] = Field(max_length=100000)
    phase: Literal["working", "idle", "shutdown"] = "idle"
    aico_session_id: str | None = None
    work_role: dict[str, str] | None = None


def _count(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def normalize_messages(messages: list[NativeMessage]) -> list[NormalizedEvent]:
    events: list[NormalizedEvent] = []
    turn = 0
    for message in sorted(messages, key=lambda row: (row.time.get("created", 0), row.id)):
        if message.type == "user":
            turn += 1
        timestamp = message.time.get("completed") or message.time.get("created")
        common = {"turn": max(turn, 1), "message_id": message.id, "surface": "opencode",
                  "source_client": "opencode-plugin",
                  "source_timestamp": datetime.fromtimestamp(timestamp / 1000, UTC) if timestamp else None}
        # Native route labels are retained as such; selection alone is never a response.
        model = message.model.label if message.model is not None else None
        def append(kind: str, suffix: str, message_id: str = message.id, base: dict[str, Any] = common, **values: Any) -> None:
            events.append(NormalizedEvent(event_type=kind, source_event_id=f"opencode:{message_id}:{suffix}",
                                          **base, **values))
        if message.type == "user":
            append("user_message", "user", role="user", content=message.text)
        elif message.type == "assistant" and message.time.get("completed"):
            for index, block in enumerate(message.content):
                kind = block.get("type")
                if kind in {"text", "reasoning"} and isinstance(block.get("text"), str):
                    append("thinking" if kind == "reasoning" else "assistant_message", str(index),
                           role="assistant", content=block["text"], model_used=model)
                elif kind == "tool":
                    state = block.get("state")
                    state = state if isinstance(state, dict) else {}
                    append("tool_use", f"{index}:call", role="assistant", model_used=model,
                           tool_name=block.get("name"), call_id=block.get("id"),
                           tool_input=state.get("input") if isinstance(state.get("input"), dict) else None)
                    if state.get("status") in {"completed", "error"}:
                        append("tool_result", f"{index}:result", role="tool", tool_name=block.get("name"),
                               call_id=block.get("id"), tool_output={"output": state.get("output"), "error": state.get("error")})
        if message.error:
            append("error", "error", content=str(message.error.get("message") or message.error.get("_tag") or "OpenCode request failed"))
        if message.tokens is not None and (message.time.get("completed") or message.type == "compaction"):
            tokens = message.tokens
            cache = tokens.get("cache")
            cache = cache if isinstance(cache, dict) else {}
            append("usage", "usage", model_used=model, usage={
                "scope": "response", "source": "opencode.session.message", "response_id": message.id,
                "input_tokens": sum(_count(value) or 0 for value in (tokens.get("input"), cache.get("read"), cache.get("write"))), "output_tokens": _count(tokens.get("output")),
                "cached_input_tokens": _count(cache.get("read")), "cache_write_tokens": _count(cache.get("write")),
                "native": {"tokens": tokens, "cost": message.cost},
                "cost_usd": message.cost,
            })
    return events


async def sync_opencode_export(db: AsyncSession, raw: object) -> dict[str, Any]:
    payload = NativeExport.model_validate(raw)
    info = payload.info
    if info.parentID:
        raise ValueError("OpenCode child and fork accounting is not supported by this adapter")
    cwd = info.location.directory
    project = await _resolve_canonical_project_id(CanonicalContextDeliveryRequest(consumer_surface="opencode", cwd=cwd))
    if not project:
        raise ValueError("OpenCode session cwd is outside registered projects")
    existing = (await db.execute(select(Session).where(Session.id == info.id))).scalar_one_or_none()
    if existing is not None and (existing.provider_metadata or {}).get("harness") != "opencode":
        raise ValueError("OpenCode cannot replace another native session")
    observed = next((message.model for message in reversed(payload.messages)
                     if message.type == "assistant" and message.time.get("completed") and not message.error and message.model), None)
    session, _ = await upsert_session(db, SessionUpsertRequest(
        session_id=info.id, project_id=project, provider=observed.providerID if observed else info.model.providerID,
        model=observed.label if observed else (existing.model if existing else "opencode/unknown"), session_type="agent", cwd=cwd,
        work_role=payload.work_role, request_source="opencode-plugin", provider_metadata={
            "harness": "opencode", "native_session_id": info.id, "aico_session_id": payload.aico_session_id or ((existing.provider_metadata or {}).get("aico_session_id") if existing else None),
            "opencode_selection": info.model.model_dump(), "native_model_label": observed.label if observed else ((existing.provider_metadata or {}).get("native_model_label") if existing else None),
            "model_evidence_source": "opencode.session.message.model", "native_outcome": info.outcome,
        }))
    result = await append_normalized_events(db, session.id,
        AppendNormalizedEventsRequest(events=normalize_messages(payload.messages)), session=session)
    await heartbeat_session(db, info.id, SessionHeartbeatRequest(
        cwd=cwd, phase=payload.phase, status="completed" if payload.phase == "shutdown" else "active",
        request_source="opencode-plugin"))
    return {"session_id": info.id, "events_appended": result.events_appended, "events_skipped": result.events_skipped}
