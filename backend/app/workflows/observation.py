"""Observation processing workflow."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from hatchet_sdk import (
    ConcurrencyExpression,
    ConcurrencyLimitStrategy,
    Context,
)
from pydantic import BaseModel

from app.hatchet_app import hatchet

logger = logging.getLogger(__name__)


class ObservationInput(BaseModel):
    request_dict: dict[str, Any]
    scope: str
    scope_id: str | None = None
    content_hash: str = ""

    def model_post_init(self, __context: Any) -> None:
        del __context
        if not self.content_hash:
            raw = (
                self.request_dict.get("content", "")
                + self.request_dict.get("title", "")
            )
            self.content_hash = hashlib.sha256(raw.encode()).hexdigest()[:16]


@hatchet.task(
    name="observation-processing",
    input_validator=ObservationInput,
    retries=3,
    backoff_factor=2.0,
    backoff_max_seconds=300,
    concurrency=ConcurrencyExpression(
        expression="input.content_hash",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_IN_PROGRESS,
    ),
)
async def observation_processing_task(input: ObservationInput, ctx: Context) -> dict[str, Any]:
    from app.services.memory.capture_handler import capture_observation
    from app.services.memory.observation_schema import ObservationRequest
    from app.services.memory.service import MemoryScope

    request = ObservationRequest(**input.request_dict)
    mem_scope = MemoryScope(input.scope)

    result = await capture_observation(request, mem_scope, input.scope_id)

    ctx.log(f"Observation processed: uuid={result.uuid} stored={result.stored}")
    return {
        "status": "success",
        "uuid": result.uuid,
        "stored": result.stored,
    }
