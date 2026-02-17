"""Zhipu AI direct adapter using OpenAI-compatible base."""

from __future__ import annotations

from app.adapters.openai_compat import OpenAICompatibleAdapter
from app.config import settings


class ZhipuAdapter(OpenAICompatibleAdapter):
    """Adapter for Zhipu AI (GLM) models via direct API."""

    provider_prefix = "zhipu"

    @property
    def provider_name(self) -> str:
        return "zhipu"

    def _get_base_url(self) -> str:
        return "https://open.bigmodel.cn/api/paas/v4"

    def _get_api_key(self, explicit_key: str | None) -> str:
        return explicit_key or settings.zhipu_api_key
