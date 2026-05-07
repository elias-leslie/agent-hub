"""Provider adapters for AI services."""

from app.adapters.base import CompletionResult, Message, ProviderAdapter
from app.adapters.claude import ClaudeAdapter
from app.adapters.codex_oauth import CodexOAuthAdapter
from app.adapters.deepseek import DeepSeekAdapter
from app.adapters.gemini import GeminiAdapter
from app.adapters.local import LocalAdapter
from app.adapters.minimax import MinimaxAdapter
from app.adapters.moonshot import MoonshotAdapter
from app.adapters.openai import OpenAIAdapter
from app.adapters.openrouter import OpenRouterAdapter
from app.adapters.xai import XAIAdapter
from app.adapters.zhipu import ZhipuAdapter

__all__ = [
    "ClaudeAdapter",
    "CodexOAuthAdapter",
    "CompletionResult",
    "DeepSeekAdapter",
    "GeminiAdapter",
    "LocalAdapter",
    "Message",
    "MinimaxAdapter",
    "MoonshotAdapter",
    "OpenAIAdapter",
    "OpenRouterAdapter",
    "ProviderAdapter",
    "XAIAdapter",
    "ZhipuAdapter",
]
