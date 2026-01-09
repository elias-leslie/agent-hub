"""Tests for response cache service."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.services.response_cache import (
    CachedResponse,
    CacheStats,
    ResponseCache,
    get_response_cache,
)


class TestCacheStats:
    """Tests for CacheStats dataclass."""

    def test_hit_rate_empty(self):
        """Test hit rate with no requests."""
        stats = CacheStats()
        assert stats.hit_rate == 0.0

    def test_hit_rate_all_hits(self):
        """Test hit rate with all hits."""
        stats = CacheStats(hits=10, misses=0, total_requests=10)
        assert stats.hit_rate == 1.0

    def test_hit_rate_all_misses(self):
        """Test hit rate with all misses."""
        stats = CacheStats(hits=0, misses=10, total_requests=10)
        assert stats.hit_rate == 0.0

    def test_hit_rate_mixed(self):
        """Test hit rate with mixed results."""
        stats = CacheStats(hits=7, misses=3, total_requests=10)
        assert stats.hit_rate == 0.7


class TestCachedResponse:
    """Tests for CachedResponse dataclass."""

    def test_to_dict(self):
        """Test serialization to dict."""
        response = CachedResponse(
            content="Hello",
            model="claude-sonnet-4-5",
            provider="claude",
            input_tokens=10,
            output_tokens=5,
            finish_reason="end_turn",
            cached_at="2026-01-06T00:00:00",
            cache_key="test-key",
        )
        data = response.to_dict()
        assert data["content"] == "Hello"
        assert data["model"] == "claude-sonnet-4-5"
        assert data["input_tokens"] == 10

    def test_from_dict(self):
        """Test deserialization from dict."""
        data = {
            "content": "Hello",
            "model": "claude-sonnet-4-5",
            "provider": "claude",
            "input_tokens": 10,
            "output_tokens": 5,
            "finish_reason": "end_turn",
            "cached_at": "2026-01-06T00:00:00",
            "cache_key": "test-key",
        }
        response = CachedResponse.from_dict(data)
        assert response.content == "Hello"
        assert response.model == "claude-sonnet-4-5"


class TestResponseCache:
    """Tests for ResponseCache class."""

    @pytest.fixture
    def mock_redis(self):
        """Mock Redis client."""
        with patch("app.services.response_cache.redis") as mock:
            mock_client = AsyncMock()
            mock.from_url.return_value = mock_client
            yield mock_client

    @pytest.fixture
    def mock_settings(self):
        """Mock settings."""
        with patch("app.services.response_cache.settings") as mock:
            mock.agent_hub_redis_url = "redis://localhost:6379/0"
            yield mock

    def test_generate_cache_key_deterministic(self, mock_settings):
        """Test that same input produces same key."""
        cache = ResponseCache()
        key1 = cache._generate_cache_key(
            model="claude-sonnet-4-5",
            messages=[{"role": "user", "content": "Hello"}],
            max_tokens=100,
            temperature=1.0,
        )
        key2 = cache._generate_cache_key(
            model="claude-sonnet-4-5",
            messages=[{"role": "user", "content": "Hello"}],
            max_tokens=100,
            temperature=1.0,
        )
        assert key1 == key2

    def test_generate_cache_key_different_inputs(self, mock_settings):
        """Test that different inputs produce different keys."""
        cache = ResponseCache()
        key1 = cache._generate_cache_key(
            model="claude-sonnet-4-5",
            messages=[{"role": "user", "content": "Hello"}],
            max_tokens=100,
            temperature=1.0,
        )
        key2 = cache._generate_cache_key(
            model="claude-sonnet-4-5",
            messages=[{"role": "user", "content": "Hi"}],  # Different content
            max_tokens=100,
            temperature=1.0,
        )
        assert key1 != key2

    @pytest.mark.asyncio
    async def test_get_cache_miss(self, mock_redis, mock_settings):
        """Test cache miss returns None."""
        mock_redis.get.return_value = None

        cache = ResponseCache()
        result = await cache.get(
            model="claude-sonnet-4-5",
            messages=[{"role": "user", "content": "Hello"}],
            max_tokens=100,
            temperature=1.0,
        )

        assert result is None
        assert cache.get_stats().misses == 1

    @pytest.mark.asyncio
    async def test_get_cache_hit(self, mock_redis, mock_settings):
        """Test cache hit returns cached response."""
        cached_data = {
            "content": "Cached hello",
            "model": "claude-sonnet-4-5",
            "provider": "claude",
            "input_tokens": 10,
            "output_tokens": 5,
            "finish_reason": "end_turn",
            "cached_at": "2026-01-06T00:00:00",
            "cache_key": "test-key",
        }
        mock_redis.get.return_value = json.dumps(cached_data)

        cache = ResponseCache()
        result = await cache.get(
            model="claude-sonnet-4-5",
            messages=[{"role": "user", "content": "Hello"}],
            max_tokens=100,
            temperature=1.0,
        )

        assert result is not None
        assert result.content == "Cached hello"
        assert cache.get_stats().hits == 1

    @pytest.mark.asyncio
    async def test_set_caches_response(self, mock_redis, mock_settings):
        """Test set stores response in Redis (primary + fallback)."""
        mock_redis.setex = AsyncMock()

        cache = ResponseCache()
        key = await cache.set(
            model="claude-sonnet-4-5",
            messages=[{"role": "user", "content": "Hello"}],
            max_tokens=100,
            temperature=1.0,
            content="Response",
            provider="claude",
            input_tokens=10,
            output_tokens=5,
        )

        assert key.startswith("agent-hub:response:")
        # Called twice: once for primary cache, once for fallback cache
        assert mock_redis.setex.call_count == 2

    @pytest.mark.asyncio
    async def test_invalidate(self, mock_redis, mock_settings):
        """Test cache invalidation."""
        mock_redis.delete.return_value = 1

        cache = ResponseCache()
        result = await cache.invalidate("agent-hub:response:test-key")

        assert result is True
        mock_redis.delete.assert_called_once_with("agent-hub:response:test-key")

    @pytest.mark.asyncio
    async def test_clear_all(self, mock_redis, mock_settings):
        """Test clearing all cache entries."""
        mock_redis.keys.return_value = ["key1", "key2", "key3"]
        mock_redis.delete.return_value = 3

        cache = ResponseCache()
        count = await cache.clear_all()

        assert count == 3

    def test_get_stats(self, mock_settings):
        """Test getting cache statistics."""
        cache = ResponseCache()
        cache._stats.hits = 5
        cache._stats.misses = 3
        cache._stats.total_requests = 8

        stats = cache.get_stats()
        assert stats.hits == 5
        assert stats.misses == 3
        assert stats.hit_rate == 0.625

    def test_reset_stats(self, mock_settings):
        """Test resetting cache statistics."""
        cache = ResponseCache()
        cache._stats.hits = 5
        cache._stats.misses = 3

        cache.reset_stats()
        stats = cache.get_stats()
        assert stats.hits == 0
        assert stats.misses == 0


class TestGetResponseCache:
    """Tests for singleton getter."""

    def test_returns_same_instance(self):
        """Test singleton behavior."""
        with patch("app.services.response_cache.settings") as mock_settings:
            mock_settings.agent_hub_redis_url = "redis://localhost:6379/0"
            # Reset singleton
            import app.services.response_cache as module

            module._response_cache = None

            cache1 = get_response_cache()
            cache2 = get_response_cache()
            assert cache1 is cache2
