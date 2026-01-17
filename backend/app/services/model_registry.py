"""Model Registry Service.

Provides centralized access to LLM model configuration with smart fallback.
- Fetches from Agent Hub API when available
- Falls back to bundled defaults when API unavailable
- Caches models for performance
"""

import logging
from dataclasses import dataclass
from typing import ClassVar

import httpx

logger = logging.getLogger(__name__)

# Bundled defaults for offline fallback
DEFAULT_MODELS = [
    {
        "id": "claude-sonnet-4-5",
        "display_name": "Claude Sonnet 4.5",
        "provider": "anthropic",
        "family": "claude-4",
        "context_window": 200000,
        "max_output_tokens": 64000,
        "input_price_per_m": 3.0,
        "output_price_per_m": 15.0,
        "capabilities": {"vision": True, "function_calling": True},
        "is_deprecated": False,
        "is_active": True,
    },
    {
        "id": "claude-opus-4-5",
        "display_name": "Claude Opus 4.5",
        "provider": "anthropic",
        "family": "claude-4",
        "context_window": 200000,
        "max_output_tokens": 64000,
        "input_price_per_m": 15.0,
        "output_price_per_m": 75.0,
        "capabilities": {"vision": True, "function_calling": True},
        "is_deprecated": False,
        "is_active": True,
    },
    {
        "id": "claude-haiku-4-5",
        "display_name": "Claude Haiku 4.5",
        "provider": "anthropic",
        "family": "claude-4",
        "context_window": 200000,
        "max_output_tokens": 64000,
        "input_price_per_m": 0.8,
        "output_price_per_m": 4.0,
        "capabilities": {"vision": True, "function_calling": True},
        "is_deprecated": False,
        "is_active": True,
    },
    {
        "id": "gemini-3-flash-preview",
        "display_name": "Gemini 3 Flash",
        "provider": "google",
        "family": "gemini-3",
        "context_window": 1000000,
        "max_output_tokens": 65536,
        "input_price_per_m": 0.075,
        "output_price_per_m": 0.30,
        "capabilities": {"vision": True, "function_calling": True},
        "is_deprecated": False,
        "is_active": True,
    },
    {
        "id": "gemini-3-pro-preview",
        "display_name": "Gemini 3 Pro",
        "provider": "google",
        "family": "gemini-3",
        "context_window": 1000000,
        "max_output_tokens": 65536,
        "input_price_per_m": 1.25,
        "output_price_per_m": 5.0,
        "capabilities": {"vision": True, "function_calling": True},
        "is_deprecated": False,
        "is_active": True,
    },
    {
        "id": "gemini-3-pro-image-preview",
        "display_name": "Gemini 3 Pro Image",
        "provider": "google",
        "family": "gemini-3",
        "context_window": 1000000,
        "max_output_tokens": 65536,
        "input_price_per_m": 1.25,
        "output_price_per_m": 5.0,
        "capabilities": {"vision": True, "image_gen": True},
        "is_deprecated": False,
        "is_active": True,
    },
]


@dataclass
class ModelInfo:
    """Model information."""

    id: str
    display_name: str
    provider: str
    family: str | None
    context_window: int
    max_output_tokens: int | None
    input_price_per_m: float | None
    output_price_per_m: float | None
    capabilities: dict
    is_deprecated: bool
    is_active: bool

    def has_capability(self, cap: str) -> bool:
        """Check if model has a capability."""
        return self.capabilities.get(cap, False) is True


class ModelRegistry:
    """Registry for LLM model configuration.

    Singleton that caches model information from Agent Hub API with
    fallback to bundled defaults.

    Usage:
        registry = ModelRegistry.get_instance()
        await registry.refresh()  # Optional: fetch latest from API
        model = registry.get("claude-sonnet-4-5")
        if model:
            print(f"Context window: {model.context_window}")
    """

    _instance: ClassVar["ModelRegistry | None"] = None
    _models: dict[str, ModelInfo]
    _api_url: str

    def __init__(self, api_url: str = "http://localhost:8003"):
        self._models = {}
        self._api_url = api_url
        self._load_defaults()

    @classmethod
    def get_instance(cls, api_url: str = "http://localhost:8003") -> "ModelRegistry":
        """Get singleton instance."""
        if cls._instance is None:
            cls._instance = ModelRegistry(api_url)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton (for testing)."""
        cls._instance = None

    def _load_defaults(self) -> None:
        """Load bundled default models."""
        for m in DEFAULT_MODELS:
            self._models[m["id"]] = ModelInfo(
                id=m["id"],
                display_name=m["display_name"],
                provider=m["provider"],
                family=m.get("family"),
                context_window=m["context_window"],
                max_output_tokens=m.get("max_output_tokens"),
                input_price_per_m=m.get("input_price_per_m"),
                output_price_per_m=m.get("output_price_per_m"),
                capabilities=m.get("capabilities", {}),
                is_deprecated=m.get("is_deprecated", False),
                is_active=m.get("is_active", True),
            )

    async def refresh(self, timeout: float = 2.0) -> bool:
        """Fetch latest models from API.

        Args:
            timeout: Request timeout in seconds

        Returns:
            True if refresh succeeded, False if using cached defaults
        """
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(f"{self._api_url}/api/models")
                resp.raise_for_status()
                data = resp.json()

                new_models = {}
                for m in data.get("models", []):
                    new_models[m["id"]] = ModelInfo(
                        id=m["id"],
                        display_name=m["display_name"],
                        provider=m["provider"],
                        family=m.get("family"),
                        context_window=m["context_window"],
                        max_output_tokens=m.get("max_output_tokens"),
                        input_price_per_m=m.get("input_price_per_m"),
                        output_price_per_m=m.get("output_price_per_m"),
                        capabilities=m.get("capabilities", {}),
                        is_deprecated=m.get("is_deprecated", False),
                        is_active=m.get("is_active", True),
                    )

                self._models = new_models
                logger.info(f"Refreshed model registry: {len(self._models)} models")
                return True

        except Exception as e:
            logger.warning(f"Failed to refresh model registry, using defaults: {e}")
            return False

    def get(self, model_id: str) -> ModelInfo | None:
        """Get model info by ID."""
        return self._models.get(model_id)

    def list_all(self) -> list[ModelInfo]:
        """List all models."""
        return list(self._models.values())

    def list_by_provider(self, provider: str) -> list[ModelInfo]:
        """List models by provider."""
        return [m for m in self._models.values() if m.provider == provider]

    def list_active(self) -> list[ModelInfo]:
        """List only active models."""
        return [m for m in self._models.values() if m.is_active]

    def get_context_window(self, model_id: str) -> int:
        """Get context window for model (with default fallback)."""
        model = self.get(model_id)
        if model:
            return model.context_window
        # Pattern match for families
        if "claude" in model_id.lower():
            return 200000
        if "gemini" in model_id.lower():
            return 1000000
        return 128000  # Conservative default

    def get_max_output_tokens(self, model_id: str) -> int:
        """Get max output tokens for model (with default fallback)."""
        model = self.get(model_id)
        if model and model.max_output_tokens:
            return model.max_output_tokens
        # Pattern match for families
        if "claude" in model_id.lower():
            return 64000
        if "gemini" in model_id.lower():
            return 65536
        return 8192  # Conservative default


def get_model_registry() -> ModelRegistry:
    """Get the global model registry instance."""
    return ModelRegistry.get_instance()
