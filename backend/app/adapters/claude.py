"""Claude adapter using Anthropic SDK."""

import logging
from typing import Any

import anthropic

from app.adapters.base import (
    AuthenticationError,
    CompletionResult,
    Message,
    ProviderAdapter,
    ProviderError,
    RateLimitError,
)
from app.config import settings

logger = logging.getLogger(__name__)


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

    async def complete(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int = 4096,
        temperature: float = 1.0,
        **kwargs: Any,
    ) -> CompletionResult:
        """Generate completion using Claude API."""
        # Extract system message if present
        system_content: str | None = None
        api_messages: list[dict[str, str]] = []

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
                "messages": api_messages,
            }
            if system_content:
                params["system"] = system_content

            # Make API call
            response = await self._client.messages.create(**params)

            # Extract content
            content = ""
            if response.content:
                for block in response.content:
                    if hasattr(block, "text"):
                        content += block.text

            return CompletionResult(
                content=content,
                model=response.model,
                provider=self.provider_name,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                finish_reason=response.stop_reason,
                raw_response=response,
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
