"""Configuration building for Gemini adapter."""

import logging
from typing import Any

from google.genai import types

from app.adapters.gemini_thinking import get_thinking_level

logger = logging.getLogger(__name__)


def build_config(
    temperature: float,
    max_tokens: int | None,
    model: str,
    response_format: dict[str, Any] | None,
    system_instruction: str | None,
    tools: Any,
    **kwargs: Any,
) -> types.GenerateContentConfig:
    """Build GenerateContentConfig from parameters.

    Args:
        temperature: Sampling temperature
        max_tokens: Maximum output tokens
        model: Model identifier
        response_format: Optional response format config with type and schema
        system_instruction: Optional system instruction
        tools: Optional tool definitions
        **kwargs: Additional config options (e.g., thinking_level)

    Returns:
        Configured GenerateContentConfig object
    """
    config_params: dict[str, Any] = {
        "temperature": temperature,
        "automatic_function_calling": types.AutomaticFunctionCallingConfig(disable=True),
    }

    if max_tokens is not None:
        config_params["max_output_tokens"] = max_tokens

    config = types.GenerateContentConfig(**config_params)

    _apply_response_format(config, response_format)
    _apply_thinking_config(config, model, kwargs.get("thinking_level"))

    if system_instruction:
        config.system_instruction = system_instruction

    if tools:
        config.tools = tools

    return config


def _apply_response_format(
    config: types.GenerateContentConfig,
    response_format: dict[str, Any] | None,
) -> None:
    """Apply structured output configuration.

    Args:
        config: Config object to modify
        response_format: Response format spec with type and optional schema
    """
    if not response_format or response_format.get("type") != "json_object":
        return

    config.response_mime_type = "application/json"
    json_schema = response_format.get("schema")

    if json_schema:
        config.response_schema = json_schema
        logger.info("Gemini structured output enabled with JSON schema")
    else:
        logger.info("Gemini structured output enabled (JSON mode without schema)")


def _apply_thinking_config(
    config: types.GenerateContentConfig,
    model: str,
    thinking_level: str | None,
) -> None:
    """Apply thinking configuration for Gemini 3 models.

    Args:
        config: Config object to modify
        model: Model identifier
        thinking_level: Optional thinking level override
    """
    level = get_thinking_level(model, thinking_level)
    if level:
        config.thinking_config = types.ThinkingConfig(thinking_level=level)
        logger.debug(f"Gemini thinking_level={level} for model={model}")
