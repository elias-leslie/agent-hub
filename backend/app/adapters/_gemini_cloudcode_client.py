"""CloudCode PA HTTP client for consumer OAuth.

Internal module — import public API from gemini_cloudcode.py.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.adapters.gemini_auth import CODE_ASSIST_ENDPOINT

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 300.0  # 5 minutes for agentic calls


class CloudCodeClient:
    """HTTP client for cloudcode-pa.googleapis.com consumer OAuth."""

    def __init__(
        self,
        access_token: str,
        refresh_token: str | None,
        project_id: str,
        expires_at: float | None = None,
        user_agent: str = "agent-hub",
        endpoint: str | None = None,
        extra_headers: dict[str, str | None] | None = None,
    ):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.project_id = project_id
        self.expires_at = expires_at
        self.user_agent = user_agent
        self.endpoint = endpoint or CODE_ASSIST_ENDPOINT
        self.extra_headers = extra_headers

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return time.time() >= (self.expires_at - 60)

    async def _ensure_token(self) -> None:
        """Refresh access token if expired, persisting to DB/cache."""
        if not self.is_expired or not self.refresh_token:
            return
        try:
            if self.user_agent == "antigravity":
                from app.adapters.gemini_auth import refresh_antigravity_token
                creds = await refresh_antigravity_token(self.refresh_token)
            else:
                from app.adapters.gemini_auth import refresh_gemini_token
                creds = await refresh_gemini_token(self.refresh_token)

            self.access_token = creds.access_token
            self.expires_at = creds.expires_at
            if creds.refresh_token:
                self.refresh_token = creds.refresh_token
            logger.debug("CloudCode: token refreshed (agent=%s)", self.user_agent)

            self._persist_refreshed_token()
        except Exception:
            logger.warning("CloudCode: token refresh failed", exc_info=True)

    def _persist_refreshed_token(self) -> None:
        """Update the in-memory credential cache with the refreshed token."""
        try:
            from app.services.credential_manager import get_credential_manager

            cm = get_credential_manager()
            if not cm.is_initialized:
                return

            provider_key = "antigravity" if self.user_agent == "antigravity" else "gemini"

            existing = cm.get(provider_key, "oauth_token")
            data = json.loads(existing) if existing else {}

            data["access_token"] = self.access_token
            data["expires_at"] = self.expires_at
            cm.set(provider_key, "oauth_token", json.dumps(data))

            if self.refresh_token:
                cm.set(provider_key, "refresh_token", self.refresh_token)

            logger.debug("CloudCode: persisted refreshed token to cache")
        except Exception:
            logger.debug("CloudCode: failed to persist token", exc_info=True)

    def _headers(self, streaming: bool = False) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "User-Agent": "google-api-nodejs-client/9.15.1",
            "X-Goog-Api-Client": "gl-node/22.17.0",
            "Client-Metadata": "ideType=IDE_UNSPECIFIED,platform=PLATFORM_UNSPECIFIED,pluginType=GEMINI",
        }
        if streaming:
            headers["Accept"] = "text/event-stream"
        if self.extra_headers:
            headers.update(self.extra_headers)
            headers = {k: v for k, v in headers.items() if v is not None}
        return headers

    def _build_request_body(
        self,
        model: str,
        contents: list[dict[str, Any]],
        system_instruction: dict[str, Any] | None = None,
        generation_config: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build the cloudcode-pa request wrapper.

        Matches the Gemini CLI's CAGenerateContentRequest format exactly:
        {model, project, request}. Extra fields like userAgent/requestType
        caused Google to misattribute quota buckets, resulting in aggressive
        rate limiting instead of honoring the user's AI Pro subscription.
        """
        request: dict[str, Any] = {"contents": contents}
        if system_instruction:
            request["systemInstruction"] = system_instruction
        if generation_config:
            request["generationConfig"] = generation_config
        if tools:
            request["tools"] = tools
        if tool_config:
            request["toolConfig"] = tool_config

        return {
            "model": model,
            "project": self.project_id,
            "request": request,
        }

    async def generate_content(
        self,
        model: str,
        contents: list[dict[str, Any]],
        system_instruction: dict[str, Any] | None = None,
        generation_config: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Non-streaming generate content."""
        await self._ensure_token()
        body = self._build_request_body(
            model, contents, system_instruction, generation_config, tools, tool_config,
        )

        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            resp = await client.post(
                f"{self.endpoint}/v1internal:generateContent",
                headers=self._headers(),
                json=body,
            )

        if resp.status_code != 200:
            msg = (
                f"CloudCode generateContent HTTP {resp.status_code}"
                f" (endpoint={self.endpoint}, model={model},"
                f" project={self.project_id}): {resp.text[:500]}"
            )
            logger.error(msg)
            raise RuntimeError(msg)

        return resp.json()

    async def stream_generate_content(
        self,
        model: str,
        contents: list[dict[str, Any]],
        system_instruction: dict[str, Any] | None = None,
        generation_config: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_config: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Streaming generate content via SSE."""
        await self._ensure_token()
        body = self._build_request_body(
            model, contents, system_instruction, generation_config, tools, tool_config,
        )

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(_REQUEST_TIMEOUT, connect=30.0),
        ) as client, client.stream(
            "POST",
            f"{self.endpoint}/v1internal:streamGenerateContent?alt=sse",
            headers=self._headers(streaming=True),
            json=body,
        ) as resp:
            if resp.status_code != 200:
                error_text = (await resp.aread()).decode(errors="replace")
                msg = f"CloudCode stream HTTP {resp.status_code}: {error_text[:500]}"
                raise RuntimeError(msg)

            buffer = ""
            async for raw_chunk in resp.aiter_text():
                buffer += raw_chunk
                lines = buffer.split("\n")
                buffer = lines.pop()

                for line in lines:
                    line = line.strip()
                    if not line.startswith("data:"):
                        continue
                    json_str = line[5:].strip()
                    if not json_str:
                        continue
                    try:
                        yield json.loads(json_str)
                    except json.JSONDecodeError:
                        logger.warning("CloudCode: bad SSE JSON: %s", json_str[:200])
