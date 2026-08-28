"""Standalone Gemini embedding service.

Provides async embedding generation using gemini-embedding-001.
Single API call per embed, no entity extraction overhead.
Includes an LRU cache for query embeddings to avoid redundant API calls.

Gemini is configured as a pool of keys belonging to separate accounts, so a key
that has been shut off (depleted prepay balance, revoked key) must not sink
every embedding that follows. Requests rotate through the pool via
``app.llm.api_key_pool``, the same rotation the chat providers use.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from functools import lru_cache
from typing import TypeVar

from google import genai

from app.llm.api_key_pool import mark_key_failure, mark_key_success, ordered_keys
from app.llm.env_api_keys import get_env_api_keys
from app.services.llm_errors import AuthenticationError

logger = logging.getLogger(__name__)

# Embedding configuration
EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIM = 768
EMBEDDING_PROVIDER = "gemini"
_EMBED_CACHE_MAX = 256

T = TypeVar("T")


def _resolve_gemini_api_keys() -> list[str]:
    """Resolve the Gemini key pool in failover order."""
    keys = get_env_api_keys(EMBEDDING_PROVIDER)
    if not keys:
        raise AuthenticationError(EMBEDDING_PROVIDER)
    return keys


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
        # An explicit key pins the service to one account; otherwise the pool is
        # resolved per request so a credential reload takes effect without a
        # restart.
        self._pinned_key = api_key
        if not api_key:
            # Fail fast when no account is configured at all, so read-side
            # callers can degrade at construction instead of at query time.
            _resolve_gemini_api_keys()
        self.model = model
        self.dim = dim
        self._clients: dict[str, genai.Client] = {}
        self._cache: OrderedDict[str, list[float]] = OrderedDict()

    def _pool_keys(self) -> list[str]:
        if self._pinned_key:
            return [self._pinned_key]
        return _resolve_gemini_api_keys()

    def _client_for(self, api_key: str) -> genai.Client:
        client = self._clients.get(api_key)
        if client is None:
            client = genai.Client(api_key=api_key)
            self._clients[api_key] = client
        return client

    async def _with_failover(
        self, call: Callable[[genai.Client], Awaitable[T]]
    ) -> T:
        """Run ``call`` against the key pool, rotating past shut-off accounts.

        A failure the pool attributes to the key itself (billing stop, revoked
        key, quota) moves on to the next account. Anything else — a malformed
        request, a model-side error — would fail identically everywhere, so it
        propagates on the first try rather than burning the whole pool.
        """
        keys = self._pool_keys()
        last_error: Exception | None = None
        for api_key in ordered_keys(EMBEDDING_PROVIDER, keys):
            try:
                result = await call(self._client_for(api_key))
            except Exception as e:
                cooldown = mark_key_failure(EMBEDDING_PROVIDER, api_key, e)
                if cooldown is None:
                    raise
                last_error = e
                logger.warning(
                    "Gemini embedding key benched for %.0fs, trying next: %s",
                    cooldown,
                    e,
                )
                continue
            mark_key_success(EMBEDDING_PROVIDER, api_key)
            return result

        assert last_error is not None  # the loop body either returns or sets it
        raise last_error

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

        result = await self._with_failover(
            lambda client: client.aio.models.embed_content(
                model=self.model,
                contents=text,
                config={"output_dimensionality": self.dim},
            )
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
        result = await self._with_failover(
            lambda client: client.aio.models.embed_content(
                model=self.model,
                contents=texts,
                config={"output_dimensionality": self.dim},
            )
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
