"""Keeps a running attempt's conversation on its session, so a step's chat fills in while the step works.

Each attempt has one follower. A short tick (``live_transcript_interval_seconds`` in the run policy) does two things:

* it records the harness's native session id and transcript path on the attempt as soon as the executor reports them
  (``workflow_attempt.native_session_id`` / ``transcript_path``), so a worker crash does not lose which file is theirs;
* for Pi, Codex and Claude Code it appends the transcript's finished records as ordinary session events
  (``native_transcript.follow_attempt_transcript``).

Agent Hub steps write their own turns as they complete (``agent_hub_transcript.TranscriptFlusher``); the follower
only records their identity. At the end of the attempt ``finish`` waits for any pass in flight and does the one full
ingest that reconciles the rows. Nothing here ends, retries or judges an attempt.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session

from .live import LiveStatus
from .native_transcript import (
    NATIVE_EXECUTORS,
    follow_attempt_transcript,
    ingest_attempt_in_own_session,
)

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class TranscriptFollower:
    def __init__(
        self,
        factory: SessionFactory,
        attempt_id: str,
        *,
        executor: str | None,
        agent_slug: str | None,
        live: LiveStatus,
        interval: float,
    ) -> None:
        self.factory, self.attempt_id, self.executor, self.agent_slug = factory, attempt_id, executor, agent_slug
        self.live, self.interval = live, interval
        self._recorded: tuple[str | None, str | None] = (None, None)
        self._lock = asyncio.Lock()
        self._stopped = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def _identify(self) -> tuple[str | None, str | None]:
        """(native session id, transcript path) as far as the executor has said; locates a file not found yet."""

        live = self.live
        if live.native_session_id and not live.transcript_path and live.locate is not None:
            try:
                found = await asyncio.to_thread(live.locate)
            except Exception:
                logger.debug("attempt %s: transcript lookup failed", self.attempt_id, exc_info=True)
                found = None
            if found:
                live.transcript_path = found
        return live.native_session_id, live.transcript_path

    async def _record_identity(self, native_session_id: str | None, transcript_path: str | None) -> None:
        if (native_session_id, transcript_path) == self._recorded or not (native_session_id or transcript_path):
            return
        async with self.factory() as db:
            attempt = await db.get(Session, self.attempt_id, with_for_update=True, populate_existing=True)
            if attempt is None:
                return
            meta = dict(attempt.provider_metadata or {})
            detail = dict(meta.get("workflow_attempt") or {})
            detail["executor"] = self.executor
            for key, value in (("native_session_id", native_session_id), ("transcript_path", transcript_path)):
                if value:
                    detail[key] = value
            attempt.provider_metadata = {**meta, "workflow_attempt": detail}
            await db.commit()
        self._recorded = (native_session_id, transcript_path)

    async def sync(self) -> int:
        """One pass: record the identity, then ingest new native records. Never raises; returns events appended."""

        async with self._lock:
            try:
                native_id, path = await self._identify()
                await self._record_identity(native_id, path)
                if self.executor not in NATIVE_EXECUTORS or not path:
                    return 0
                async with self.factory() as db:
                    return await follow_attempt_transcript(
                        db,
                        self.attempt_id,
                        executor=self.executor,
                        transcript_path=path,
                        native_session_id=native_id,
                        agent_slug=self.agent_slug,
                    )
            except Exception:
                logger.warning("attempt %s: live transcript pass failed", self.attempt_id, exc_info=True)
                return 0

    async def finish(
        self, *, transcript_path: str | None, native_session_id: str | None
    ) -> dict[str, Any] | None:
        """The attempt's last ingest, after any pass in flight: the whole file, so the rows match a one-shot ingest."""

        async with self._lock:
            return await ingest_attempt_in_own_session(
                self.factory,
                self.attempt_id,
                executor=self.executor,
                transcript_path=transcript_path,
                native_session_id=native_session_id,
                agent_slug=self.agent_slug,
            )

    async def _loop(self) -> None:
        while not self._stopped.is_set():
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stopped.wait(), self.interval)
                return
            await self.sync()

    async def __aenter__(self) -> TranscriptFollower:
        self._task = asyncio.create_task(self._loop())
        return self

    async def __aexit__(self, *_exc: object) -> None:
        self._stopped.set()
        if self._task is not None:
            try:
                await self._task
            except BaseException:
                self._task.cancel()
                raise
