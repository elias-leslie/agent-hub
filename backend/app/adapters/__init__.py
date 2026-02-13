"""Provider adapters for AI services."""

from app.adapters.base import CompletionResult, Message, ProviderAdapter
from app.adapters.claude import ClaudeAdapter
from app.adapters.gemini import GeminiAdapter
from app.adapters.minimax import MinimaxAdapter
from app.adapters.openai import OpenAIAdapter
from app.adapters.openrouter import OpenRouterAdapter
from app.adapters.xai import XAIAdapter
from app.adapters.zhipu import ZhipuAdapter

__all__ = [
    "ClaudeAdapter",
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
