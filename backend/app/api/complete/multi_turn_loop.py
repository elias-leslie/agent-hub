"""Turn loop execution for multi-turn completions."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from app.adapters.base import Message
from app.services.container_manager import ContainerManager

from .finish_reason_handler import handle_finish_reason
from .multi_turn_helpers import TurnLoopConfig, process_turn_result
from .turn_processor import create_progress, report_progress

logger = logging.getLogger(__name__)


async def run_adapter_turn(
    cfg: TurnLoopConfig,
    turn: int,
    current_container_id: str | None,
) -> tuple[Any, int]:
    """Call the adapter for one turn and return (result, duration_ms)."""
    turn_start = time.monotonic()
    result = await cfg.adapter.complete(
        messages=cfg.messages_for_adapter,
        model=cfg.model,
        max_tokens=None,
        temperature=cfg.temperature,
        enable_caching=cfg.enable_caching if turn == 1 else False,
        cache_ttl=cfg.cache_ttl,
        thinking_level=cfg.thinking_level,
        tools=cfg.tools,
        enable_programmatic_tools=cfg.enable_programmatic_tools,
        container_id=current_container_id,
        response_format=cfg.response_format,
        working_dir=cfg.working_dir,
    )
    return result, int((time.monotonic() - turn_start) * 1000)


async def _maybe_compact(cfg: TurnLoopConfig, turn: int) -> None:
    """Compact context in-place on cfg if needed (turn > 1 only)."""
    if turn <= 1:
        return
    from .context_compaction import maybe_compact_context

    cfg.messages_dict, was_compacted = await maybe_compact_context(
        cfg.messages_dict, cfg.model, session_id=cfg.session_id, db=cfg.db,
    )
    if was_compacted:
        cfg.messages_for_adapter[:] = [
            Message(role=m["role"], content=m["content"]) for m in cfg.messages_dict
        ]
        logger.info("Context compacted at turn %d", turn)


async def execute_single_turn(
    cfg: TurnLoopConfig,
    turn: int,
    state: dict[str, Any],
    container_manager: ContainerManager,
) -> bool:
    """Execute one turn; return True if the loop should stop."""
    await _maybe_compact(cfg, turn)

    progress = create_progress(turn, "running", f"Turn {turn}: sending to {cfg.provider}")
    state["progress_log"].append(progress)
    await report_progress(progress, cfg.progress_callback)

    result, turn_duration_ms = await run_adapter_turn(cfg, turn, state["current_container_id"])
    await process_turn_result(
        result, turn, state, container_manager, cfg.db, cfg.session_id,
        cfg.model, cfg.user_messages_for_db, cfg.messages_dict, cfg.temperature,
        cfg.skip_cache, cfg.cache, cfg.loaded_memory_uuids, cfg.memory_group_id,
        cfg.agent_slug, turn_duration_ms,
    )
    should_break, state["execution_status"], state["execution_error"] = await handle_finish_reason(
        result.finish_reason, turn, cfg.max_turns, result,
        cfg.messages_for_adapter, state["progress_log"], cfg.progress_callback,
    )
    return should_break


async def _run_one_turn_with_timeout(
    cfg: TurnLoopConfig,
    turn: int,
    state: dict[str, Any],
    container_manager: ContainerManager,
) -> bool:
    """Run execute_single_turn, applying per_turn_timeout if set."""
    coro = execute_single_turn(cfg, turn, state, container_manager)
    if not cfg.per_turn_timeout:
        return await coro
    try:
        return await asyncio.wait_for(coro, timeout=cfg.per_turn_timeout)
    except TimeoutError:
        raise TimeoutError(
            f"Turn {turn} timed out after {cfg.per_turn_timeout:.0f}s "
            f"(model={cfg.model}, session={cfg.session_id}). "
            f"Agent may be stuck — no progress for {cfg.per_turn_timeout:.0f}s."
        ) from None


_CHECKPOINT_MSG = (
    "<system-checkpoint>"
    "Turn {turn} checkpoint — this is NOT a signal to stop. "
    "You have plenty of capacity remaining. Quick self-check: "
    "(1) Am I making forward progress or repeating myself? "
    "(2) Am I stuck on something I should delegate or skip? "
    "If progressing: keep going, finish what you're doing. "
    "If looping: change approach or move on. "
    "Resume your work now."
    "</system-checkpoint>"
)


def _needs_checkpoint(turn: int, soft_limit: int | None, interval: int) -> bool:
    """Return True if a checkpoint message should be injected at this turn."""
    if not soft_limit or turn < soft_limit:
        return False
    return (turn - soft_limit) % interval == 0


async def run_turn_loop(
    cfg: TurnLoopConfig,
    state: dict[str, Any],
    container_manager: ContainerManager,
) -> None:
    """Run the multi-turn loop, updating state in place.

    Args:
        cfg: Immutable config for the loop (adapter, model, tools, db, etc.).
        state: Mutable execution state updated after each turn.
        container_manager: Tracks container lifecycle.
    """
    for turn in range(1, cfg.max_turns + 1):
        if _needs_checkpoint(turn, cfg.soft_limit, cfg.soft_limit_interval):
            checkpoint = _CHECKPOINT_MSG.format(turn=turn)
            cfg.messages_for_adapter.append(Message(role="user", content=checkpoint))
            cfg.messages_dict.append({"role": "user", "content": checkpoint})
            logger.info("Soft-limit checkpoint injected at turn %d", turn)

        should_break = await _run_one_turn_with_timeout(cfg, turn, state, container_manager)
        if should_break:
            break
