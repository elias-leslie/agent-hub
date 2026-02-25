"""Provider adapters for AI services."""

from app.adapters import sdk_compat as _sdk_compat
from app.adapters.base import CompletionResult, Message, ProviderAdapter
from app.adapters.claude import ClaudeAdapter
from app.adapters.codex_oauth import CodexOAuthAdapter
from app.adapters.gemini import GeminiAdapter
from app.adapters.minimax import MinimaxAdapter
from app.adapters.openai import OpenAIAdapter
from app.adapters.openrouter import OpenRouterAdapter
from app.adapters.xai import XAIAdapter
from app.adapters.zhipu import ZhipuAdapter

_sdk_compat.patch()

__all__ = [
    "ClaudeAdapter",
    "CodexOAuthAdapter",
    "CompletionResult",
    "GeminiAdapter",
    "Message",
    "MinimaxAdapter",
    "OpenAIAdapter",
    "OpenRouterAdapter",
    "ProviderAdapter",
    "XAIAdapter",
    "ZhipuAdapter",
]
