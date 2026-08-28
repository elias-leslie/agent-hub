"""Tests for EmbedderService query cache."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.memory.embedder import _EMBED_CACHE_MAX, EmbedderService


def _make_embed_result(values: list[float]) -> SimpleNamespace:
    return SimpleNamespace(embeddings=[SimpleNamespace(values=values)])


@pytest.fixture
def client() -> MagicMock:
    return MagicMock()


@pytest.fixture
def embedder(client: MagicMock) -> EmbedderService:
    svc = EmbedderService(api_key="test-key")
    svc._clients["test-key"] = client
    return svc


@pytest.mark.asyncio
async def test_embed_caches_result(embedder: EmbedderService, client: MagicMock) -> None:
    vec = [0.1, 0.2, 0.3]
    client.aio.models.embed_content = AsyncMock(
        return_value=_make_embed_result(vec)
    )

    result1 = await embedder.embed("hello world")
    result2 = await embedder.embed("hello world")

    assert result1 == vec
    assert result2 == vec
    # Only one API call despite two embed() calls
    client.aio.models.embed_content.assert_awaited_once()


@pytest.mark.asyncio
async def test_embed_cache_different_keys(
    embedder: EmbedderService, client: MagicMock
) -> None:
    client.aio.models.embed_content = AsyncMock(
        side_effect=[
            _make_embed_result([0.1]),
            _make_embed_result([0.2]),
        ]
    )

    r1 = await embedder.embed("query A")
    r2 = await embedder.embed("query B")

    assert r1 == [0.1]
    assert r2 == [0.2]
    assert client.aio.models.embed_content.await_count == 2


@pytest.mark.asyncio
async def test_embed_cache_eviction(embedder: EmbedderService, client: MagicMock) -> None:
    call_count = 0

    async def _mock_embed(**kwargs):
        nonlocal call_count
        call_count += 1
        return _make_embed_result([float(call_count)])

    client.aio.models.embed_content = _mock_embed

    # Fill cache beyond max
    for i in range(_EMBED_CACHE_MAX + 1):
        await embedder.embed(f"query-{i}")

    assert len(embedder._cache) == _EMBED_CACHE_MAX

    # First entry should have been evicted
    assert "query-0" not in embedder._cache
    # Last entry should still be cached
    assert f"query-{_EMBED_CACHE_MAX}" in embedder._cache
