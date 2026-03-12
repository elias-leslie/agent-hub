"""Turn loop execution for multi-turn completions."""

from __future__ import annotations

import logging
import time
from typing import Any

from app.adapters.base import Message
from app.services.container_manager import ContainerManager
from app.services.context_tracker import format_budget_message
from app.services.health_prober import record_provider_failure, record_provider_success
from app.services.session_health import update_session_health
from app.services.token_counter import get_context_limit

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
    await update_session_health(cfg.db, cfg.session_id, "calling_model", commit=True)
    turn_start = time.monotonic()
    try:
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
    except Exception as exc:
        record_provider_failure(cfg.provider, str(exc), (time.monotonic() - turn_start) * 1000)
        raise
    duration_ms = int((time.monotonic() - turn_start) * 1000)
    record_provider_success(cfg.provider, duration_ms)
    return result, duration_ms


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
    await update_session_health(cfg.db, cfg.session_id, "processing_response", commit=True)
    await process_turn_result(
        result, turn, state, container_manager, cfg.db, cfg.session_id,
        cfg.model, cfg.user_messages_for_db, cfg.messages_dict, cfg.temperature,
        cfg.skip_cache, cfg.cache, cfg.loaded_memory_uuids, cfg.memory_group_id,
        cfg.agent_slug, turn_duration_ms,
    )

    # Inject token budget awareness after each turn
    budget_msg = format_budget_message(
        result.input_tokens, get_context_limit(cfg.model),
        emitted_thresholds=state.setdefault("_budget_thresholds", set()),
    )
    if budget_msg:
        cfg.messages_for_adapter.append(Message(role="user", content=budget_msg))
        cfg.messages_dict.append({"role": "user", "content": budget_msg})
        logger.info("Budget message injected at turn %d: %s", turn, budget_msg)

    should_break, state["execution_status"], state["execution_error"] = await handle_finish_reason(
        result.finish_reason, turn, cfg.max_turns, result,
        cfg.messages_for_adapter, cfg.messages_dict, state["progress_log"], cfg.progress_callback,
        state, cfg.agent_slug, cfg.task_type, cfg.hard_cap,
    )
    return should_break


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

_WRAPUP_MSG = (
    "<system-wrapup>"
    "Turn {turn} — you have reached your turn limit. "
    "Stop starting new work. Wrap up: "
    "(1) Commit any uncommitted changes. "
    "(2) Update task status (st done / st abandon). "
    "(3) Write a brief summary of what you accomplished. "
    "(4) File any feedback ([[F:type:component:description]]). "
    "You have a small grace period for cleanup, then execution stops."
    "</system-wrapup>"
)


def _needs_checkpoint(turn: int, soft_limit: int, interval: int) -> bool:
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

    Turn timeline (for max_turns=200):
        1-99:    Normal execution
        100:     Checkpoint #1 (soft_limit)
        125-175: Checkpoints #2-#4
        200:     Wrap-up message — stop new work, commit, summarize
        201-220: Grace period (agent wraps up)
        220:     Hard stop — loop terminates
    """
    for turn in range(1, cfg.hard_cap + 1):
        # Wrap-up takes priority over checkpoint at the same turn
        if cfg.wrapup_turn and turn == cfg.wrapup_turn:
            wrapup = _WRAPUP_MSG.format(turn=turn)
            cfg.messages_for_adapter.append(Message(role="user", content=wrapup))
            cfg.messages_dict.append({"role": "user", "content": wrapup})
            logger.info("Wrap-up message injected at turn %d", turn)
        elif _needs_checkpoint(turn, cfg.soft_limit, cfg.checkpoint_interval):
            checkpoint = _CHECKPOINT_MSG.format(turn=turn)
            cfg.messages_for_adapter.append(Message(role="user", content=checkpoint))
            cfg.messages_dict.append({"role": "user", "content": checkpoint})
            logger.info("Soft-limit checkpoint injected at turn %d", turn)

        should_break = await execute_single_turn(cfg, turn, state, container_manager)
        if should_break:
            break
