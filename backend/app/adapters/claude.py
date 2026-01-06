"""Claude adapter using Anthropic SDK."""

import logging
from typing import Any, Literal

import anthropic

from app.adapters.base import (
    AuthenticationError,
    CacheMetrics,
    CompletionResult,
    Message,
    ProviderAdapter,
    ProviderError,
    RateLimitError,
)
from app.config import settings

logger = logging.getLogger(__name__)

# Cache TTL types supported by Anthropic
CacheTTL = Literal["ephemeral", "1h"]


class ClaudeAdapter(ProviderAdapter):
    """Adapter for Claude models via Anthropic API."""

    def __init__(self, api_key: str | None = None):
        """
        Initialize Claude adapter.

        Args:
            api_key: Anthropic API key. Falls back to settings if not provided.
        """
        self._api_key = api_key or settings.anthropic_api_key
        if not self._api_key:
            raise ValueError("Anthropic API key not configured")
        self._client = anthropic.AsyncAnthropic(api_key=self._api_key)

    @property
    def provider_name(self) -> str:
        return "claude"

    def _prepare_messages_with_cache(
        self,
        messages: list[dict[str, Any]],
        enable_caching: bool,
        cache_ttl: CacheTTL,
    ) -> list[dict[str, Any]]:
        """
        Prepare messages with cache breakpoints.

        Adds cache_control to the last user message for multi-turn caching.
        This allows the conversation context to be cached and reused.
        """
        if not enable_caching or not messages:
            return messages

        # Find the last user message and add cache control
        result = []
        last_user_idx = -1
        for i, msg in enumerate(messages):
            if msg.get("role") == "user":
                last_user_idx = i

        for i, msg in enumerate(messages):
            if i == last_user_idx and msg.get("role") == "user":
                # Convert simple content to content blocks with cache_control
                content = msg.get("content", "")
                if isinstance(content, str):
                    result.append(
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": content,
                                    "cache_control": {"type": cache_ttl},
                                }
                            ],
                        }
                    )
                else:
                    # Already a list of content blocks, add cache to last text block
                    new_content = []
                    for j, block in enumerate(content):
                        if j == len(content) - 1 and block.get("type") == "text":
                            new_content.append(
                                {**block, "cache_control": {"type": cache_ttl}}
                            )
                        else:
                            new_content.append(block)
                    result.append({"role": "user", "content": new_content})
            else:
                result.append(msg)

        return result

    async def complete(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int = 4096,
        temperature: float = 1.0,
        enable_caching: bool = True,
        cache_ttl: CacheTTL = "ephemeral",
        **kwargs: Any,
    ) -> CompletionResult:
        """
        Generate completion using Claude API.

        Args:
            messages: Conversation messages
            model: Model identifier
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature
            enable_caching: Enable prompt caching (default True)
            cache_ttl: Cache TTL - "ephemeral" (5min) or "1h" (1 hour)
            **kwargs: Additional parameters

        Returns:
            CompletionResult with cache metrics if caching enabled
        """
        # Extract system message and build API messages
        system_content: str | None = None
        api_messages: list[dict[str, Any]] = []

        for msg in messages:
            if msg.role == "system":
                system_content = msg.content
            else:
                api_messages.append({"role": msg.role, "content": msg.content})

        try:
            # Build request params
            params: dict[str, Any] = {
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": self._prepare_messages_with_cache(
                    api_messages, enable_caching, cache_ttl
                ),
            }

            # Add system message with cache control
            if system_content:
                if enable_caching:
                    params["system"] = [
                        {
                            "type": "text",
                            "text": system_content,
                            "cache_control": {"type": cache_ttl},
                        }
                    ]
                else:
                    params["system"] = system_content

            # Make API call
            response = await self._client.messages.create(**params)

            # Extract content
            content = ""
            if response.content:
                for block in response.content:
                    if hasattr(block, "text"):
                        content += block.text

            # Extract cache metrics
            cache_metrics = None
            if enable_caching:
                cache_metrics = CacheMetrics(
                    cache_creation_input_tokens=getattr(
                        response.usage, "cache_creation_input_tokens", 0
                    )
                    or 0,
                    cache_read_input_tokens=getattr(
                        response.usage, "cache_read_input_tokens", 0
                    )
                    or 0,
                )
                if cache_metrics.cache_read_input_tokens > 0:
                    logger.info(
                        f"Cache hit: {cache_metrics.cache_read_input_tokens} tokens "
                        f"({cache_metrics.cache_hit_rate:.1%} hit rate)"
                    )

            return CompletionResult(
                content=content,
                model=response.model,
                provider=self.provider_name,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                finish_reason=response.stop_reason,
                raw_response=response,
                cache_metrics=cache_metrics,
            )

        except anthropic.RateLimitError as e:
            logger.warning(f"Claude rate limit: {e}")
            # Try to extract retry-after from response
            retry_after = None
            if hasattr(e, "response") and e.response:
                retry_after_str = e.response.headers.get("retry-after")
                if retry_after_str:
                    try:
                        retry_after = float(retry_after_str)
                    except ValueError:
                        pass
            raise RateLimitError(self.provider_name, retry_after) from e

        except anthropic.AuthenticationError as e:
            logger.error(f"Claude auth error: {e}")
            raise AuthenticationError(self.provider_name) from e

        except anthropic.APIError as e:
            logger.error(f"Claude API error: {e}")
            raise ProviderError(
                str(e),
                provider=self.provider_name,
                retriable=getattr(e, "status_code", 500) >= 500,
                status_code=getattr(e, "status_code", None),
            ) from e

    async def health_check(self) -> bool:
        """Check if Claude API is reachable."""
        try:
            # Use a minimal request to check connectivity
            await self._client.messages.create(
                model="claude-haiku-4-5-20250514",
                max_tokens=10,
                messages=[{"role": "user", "content": "ping"}],
            )
            return True
        except Exception as e:
            logger.warning(f"Claude health check failed: {e}")
            return False
