"""SDK options builder for Claude adapter."""

import logging
from typing import Any

from app.adapters._claude_constants import DEFAULT_ALLOWED_CLI_TOOLS, THINKING_LEVEL_TO_EFFORT

logger = logging.getLogger(__name__)


def _get_thinking_config(thinking_level: str | None) -> Any:
    """Convert thinking_level to Claude SDK ThinkingConfig dict."""
    if not thinking_level:
        return None
    effort = THINKING_LEVEL_TO_EFFORT.get(thinking_level)
    if effort is None:
        return {"type": "disabled"}
    return {"type": "adaptive", "effort": effort}


def _apply_permission_opts(
    sdk_opts: dict[str, Any],
    yolo_mode: bool,
    can_use_tool: Any | None,
) -> bool:
    """Configure permission settings; returns use_streaming_prompt flag."""
    if yolo_mode and can_use_tool is None:
        sdk_opts["permission_mode"] = "bypassPermissions"
        return False
    if can_use_tool is not None:
        sdk_opts["can_use_tool"] = can_use_tool
        return True
    return False


def _apply_optional_opts(
    sdk_opts: dict[str, Any],
    thinking_level: str | None,
    max_turns: int | None,
    json_mode: bool,
    json_schema: dict[str, Any] | None,
    resume_session_id: str | None,
    mcp_servers: dict[str, Any] | None,
    system_prompt: str | None,
) -> bool:
    """Apply optional SDK options; returns use_streaming_prompt flag."""
    use_streaming_prompt = False

    thinking = _get_thinking_config(thinking_level)
    if thinking is not None:
        sdk_opts["thinking"] = thinking

    if max_turns is not None:
        sdk_opts["max_turns"] = max_turns

    if json_mode and json_schema:
        sdk_opts["output_format"] = {"type": "json_schema", "schema": json_schema}
        sdk_opts["max_turns"] = 2  # json_mode always overrides

    if resume_session_id:
        sdk_opts["resume"] = resume_session_id
        logger.info("SDK options: resuming session %s", resume_session_id)

    if mcp_servers:
        sdk_opts["mcp_servers"] = mcp_servers
        use_streaming_prompt = True

    if system_prompt:
        sdk_opts["system_prompt"] = system_prompt

    return use_streaming_prompt


def build_sdk_options(
    cli_path: str,
    model: str,
    model_map: dict[str, str],
    working_dir: str | None = None,
    yolo_mode: bool = True,
    can_use_tool: Any | None = None,
    mcp_servers: dict[str, Any] | None = None,
    resume_session_id: str | None = None,
    json_mode: bool = False,
    json_schema: dict[str, Any] | None = None,
    thinking_level: str | None = None,
    max_turns: int | None = None,
    allowed_tools: list[str] | None = None,
    system_prompt: str | None = None,
) -> tuple[Any, bool]:
    """Build ClaudeAgentOptions. Returns (options, use_streaming_prompt).

    Unified builder for all Claude adapter paths (oauth, streaming, tools).
    Pre-built ``can_use_tool`` callbacks and ``mcp_servers`` dicts are passed
    in by callers that need tool-specific SDK features.
    """
    from claude_agent_sdk import ClaudeAgentOptions

    from app.services.tools.project_env import build_venv_env_overlay

    cwd = working_dir or "."
    sdk_opts: dict[str, Any] = {
        "cwd": cwd,
        "cli_path": cli_path,
        "model": model_map.get(model, model),
        "env": build_venv_env_overlay(cwd),
        "enable_file_checkpointing": True,
        "max_buffer_size": 10 * 1024 * 1024,  # 10 MB
        "max_budget_usd": 5.0,
    }

    use_streaming_prompt = _apply_permission_opts(sdk_opts, yolo_mode, can_use_tool)
    use_streaming_prompt |= _apply_optional_opts(
        sdk_opts,
        thinking_level=thinking_level,
        max_turns=max_turns,
        json_mode=json_mode,
        json_schema=json_schema,
        resume_session_id=resume_session_id,
        mcp_servers=mcp_servers,
        system_prompt=system_prompt,
    )

    sdk_opts["allowed_tools"] = allowed_tools or DEFAULT_ALLOWED_CLI_TOOLS
    return ClaudeAgentOptions(**sdk_opts), use_streaming_prompt
