"""Standalone Gemini embedding service.

Provides async embedding generation using gemini-embedding-001.
Single API call per embed, no entity extraction overhead.
Includes an LRU cache for query embeddings to avoid redundant API calls.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from functools import lru_cache

from google import genai

from app.services.llm_errors import AuthenticationError

logger = logging.getLogger(__name__)

# Embedding configuration
EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIM = 768
_EMBED_CACHE_MAX = 256


def _resolve_gemini_api_key() -> str:
    """Resolve Gemini API key from credential manager."""
    from app.services.credential_manager import get_credential_manager

    cm = get_credential_manager()
    if cm.is_initialized:
        key = cm.get_api_key("gemini")
        if key:
            return key
    raise AuthenticationError("gemini")


class EmbedderService:
    """Standalone Gemini embedding service.

    One API call per embed. No LLM entity extraction.
    Uses gemini-embedding-001 with 768-dim output (Matryoshka truncation).
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = EMBEDDING_MODEL,
        dim: int = EMBEDDING_DIM,
    ) -> None:
        self._api_key = api_key or _resolve_gemini_api_key()
        self.model = model
        self.dim = dim
        self._client = genai.Client(api_key=self._api_key)
        self._cache: OrderedDict[str, list[float]] = OrderedDict()

    async def embed(self, text: str) -> list[float]:
        """Generate embedding vector for text.

        Results are cached (LRU, up to _EMBED_CACHE_MAX entries) to avoid
        redundant Gemini API calls for repeated queries within a session.

        Args:
            text: Text to embed (will be truncated if too long)

        Returns:
            768-dimensional float vector
        """
        cached = self._cache.get(text)
        if cached is not None:
            self._cache.move_to_end(text)
            return cached

        result = await self._client.aio.models.embed_content(
            model=self.model,
            contents=text,
            config={"output_dimensionality": self.dim},
        )
        assert result.embeddings is not None  # guaranteed by API contract
        vec = list(result.embeddings[0].values)

        self._cache[text] = vec
        if len(self._cache) > _EMBED_CACHE_MAX:
            self._cache.popitem(last=False)

        return vec

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts.

        Args:
            texts: List of texts to embed

        Returns:
            List of 768-dimensional float vectors
        """
        if not texts:
            return []
        result = await self._client.aio.models.embed_content(
            model=self.model,
            contents=texts,
            config={"output_dimensionality": self.dim},
        )
        assert result.embeddings is not None  # guaranteed by API contract
        return [list(e.values) for e in result.embeddings]


@lru_cache
def get_embedder() -> EmbedderService:
    """Get cached singleton EmbedderService instance."""
    return EmbedderService()


def get_embedder_or_none(operation: str) -> EmbedderService | None:
    """Return the embedder when available, otherwise degrade read-side flows."""
    try:
        return get_embedder()
    except AuthenticationError as exc:
        logger.warning("Gemini embedder unavailable for %s: %s", operation, exc)
        return None
