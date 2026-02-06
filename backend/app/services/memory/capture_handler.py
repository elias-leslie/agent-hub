from __future__ import annotations

import asyncio
import logging

from graphiti_core.utils.datetime_utils import utc_now

from .episode_creator import get_episode_creator
from .ingestion_config import CHAT_STREAM, LEARNING, TOOL_DISCOVERY, TOOL_GOTCHA, IngestionConfig
from .observation_schema import ObservationRequest, ObservationResponse, ObservationType
from .privacy_filter import apply_privacy_filter
from .service import MemoryScope

logger = logging.getLogger(__name__)

_background_tasks: set[asyncio.Task[None]] = set()

_TYPE_TO_CONFIG: dict[ObservationType, IngestionConfig] = {
    ObservationType.TOOL_USE: TOOL_DISCOVERY,
    ObservationType.LEARNING: LEARNING,
    ObservationType.ERROR: TOOL_GOTCHA,
    ObservationType.DECISION: CHAT_STREAM,
    ObservationType.CHANGE: CHAT_STREAM,
    ObservationType.PATTERN: TOOL_DISCOVERY,
}


def _build_observation_source_description(request: ObservationRequest) -> str:
    parts = [
        f"observation:{request.source.value}",
        f"type:{request.type.value}",
    ]
    if request.session_id:
        parts.append(f"session:{request.session_id}")
    if request.task_id:
        parts.append(f"task:{request.task_id}")
    if request.provider:
        parts.append(f"provider:{request.provider}")
    if request.model:
        parts.append(f"model:{request.model}")
    if request.files_modified:
        parts.append(f"files_modified:{','.join(request.files_modified[:5])}")
    if request.files_read:
        parts.append(f"files_read:{','.join(request.files_read[:5])}")
    if request.concepts:
        parts.append(f"concepts:{','.join(request.concepts[:5])}")
    return " ".join(parts)


async def capture_observation(
    request: ObservationRequest,
    scope: MemoryScope,
    scope_id: str | None,
) -> ObservationResponse:
    filtered_content, content_stats = apply_privacy_filter(request.content)

    filtered_narrative: str | None = None
    if request.narrative:
        filtered_narrative, _ = apply_privacy_filter(request.narrative)

    body_parts = [f"[{request.title}]", filtered_content]
    if filtered_narrative:
        body_parts.append(f"Context: {filtered_narrative}")
    episode_body = "\n".join(body_parts)

    config = _TYPE_TO_CONFIG.get(request.type, LEARNING)

    now = utc_now()
    episode_name = f"{request.source.value}_{request.type.value}_{now.isoformat()}"

    source_description = _build_observation_source_description(request)

    if content_stats["private_tags_stripped"] > 0:
        logger.info(
            "Privacy filter stripped %d private tag(s) from observation",
            content_stats["private_tags_stripped"],
        )

    creator = get_episode_creator(scope, scope_id)
    result = await creator.create(
        content=episode_body,
        name=episode_name,
        config=config,
        source_description=source_description,
        reference_time=now,
    )

    if result.success:
        # Broadcast to SSE capture stream (fire-and-forget)
        try:
            from .capture_stream import CaptureEvent, get_capture_stream

            stream = get_capture_stream()
            capture_event = CaptureEvent(
                event_type="observation",
                timestamp=now.isoformat(),
                data={
                    "uuid": result.uuid or "",
                    "title": request.title,
                    "content": filtered_content[:200],
                    "source": request.source.value,
                    "type": request.type.value,
                    "session_id": request.session_id,
                    "stored": True,
                },
            )
            asyncio.create_task(stream.broadcast(capture_event))
        except Exception:
            pass  # Never fail observation capture for SSE broadcast

        return ObservationResponse(
            uuid=result.uuid or "",
            stored=True,
            message="Observation captured successfully",
            episode_name=episode_name,
        )

    return ObservationResponse(
        uuid="",
        stored=False,
        message=f"Failed to capture observation: {result.validation_error or 'unknown error'}",
        episode_name=episode_name,
    )
