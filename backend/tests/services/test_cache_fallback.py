"""Tests for cache fallback functionality during provider outages."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.response_cache import (
    CACHE_PREFIX,
    FALLBACK_PREFIX,
    STALE_IF_ERROR_TTL,
    CachedResponse,
    CacheStats,
    ResponseCache,
)


class TestCacheStatsWithFallback:
    """Tests for CacheStats with fallback tracking."""

    def test_fallback_stats_default(self):
        """Test default fallback stats values."""
        stats = CacheStats()
        assert stats.fallback_hits == 0
        assert stats.fallback_misses == 0
        assert stats.fallback_usage == 0

    def test_fallback_usage_property(self):
        """Test fallback_usage property returns fallback_hits."""
        stats = CacheStats(fallback_hits=5, fallback_misses=2)
        assert stats.fallback_usage == 5


class TestCachedResponseWithFallback:
    """Tests for CachedResponse with fallback flag."""

    def test_is_fallback_default_false(self):
        """Test is_fallback defaults to False."""
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
        assert response.is_fallback is False

    def test_is_fallback_in_to_dict(self):
        """Test is_fallback is included in to_dict."""
        response = CachedResponse(
            content="Hello",
            model="claude-sonnet-4-5",
            provider="claude",
            input_tokens=10,
            output_tokens=5,
            finish_reason="end_turn",
            cached_at="2026-01-06T00:00:00",
            cache_key="test-key",
            is_fallback=True,
        )
        data = response.to_dict()
        assert data["is_fallback"] is True

    def test_is_fallback_from_dict(self):
        """Test is_fallback is parsed from dict."""
        data = {
            "content": "Hello",
            "model": "claude-sonnet-4-5",
            "provider": "claude",
            "input_tokens": 10,
            "output_tokens": 5,
            "finish_reason": "end_turn",
            "cached_at": "2026-01-06T00:00:00",
            "cache_key": "test-key",
            "is_fallback": True,
        }
        response = CachedResponse.from_dict(data)
        assert response.is_fallback is True

    def test_is_fallback_from_dict_missing(self):
        """Test is_fallback defaults to False when not in dict."""
        data = {
            "content": "Hello",
            "model": "claude-sonnet-4-5",
            "provider": "claude",
            "input_tokens": 10,
            "output_tokens": 5,
            "cached_at": "2026-01-06T00:00:00",
            "cache_key": "test-key",
        }
        response = CachedResponse.from_dict(data)
        assert response.is_fallback is False


class TestResponseCacheFallback:
    """Tests for ResponseCache fallback functionality."""

    @pytest.fixture
    def mock_redis(self):
        """Create mock Redis client."""
        mock = MagicMock()
        mock.get = AsyncMock(return_value=None)
        mock.setex = AsyncMock()
        mock.delete = AsyncMock(return_value=1)
        mock.keys = AsyncMock(return_value=[])
        mock.close = AsyncMock()
        return mock

    @pytest.fixture
    def cache(self, mock_redis):
        """Create ResponseCache with mock Redis."""
        cache = ResponseCache()
        cache._client = mock_redis
        return cache

    @pytest.fixture
    def sample_messages(self):
        """Sample messages for testing."""
        return [{"role": "user", "content": "Hello"}]

    @pytest.mark.asyncio
    async def test_set_stores_in_fallback_cache(self, cache, mock_redis, sample_messages):
        """Test that set() stores in both primary and fallback cache."""
        await cache.set(
            model="claude-sonnet-4-5",
            messages=sample_messages,
            temperature=0.7,
            content="Hello!",
            provider="claude",
            input_tokens=10,
            output_tokens=5,
        )

        assert mock_redis.setex.call_count == 2

        calls = mock_redis.setex.call_args_list
        primary_call = calls[0]
        fallback_call = calls[1]

        assert CACHE_PREFIX in primary_call[0][0]
        assert FALLBACK_PREFIX in fallback_call[0][0]
        assert fallback_call[0][1] == STALE_IF_ERROR_TTL

    @pytest.mark.asyncio
    async def test_set_with_custom_stale_ttl(self, cache, mock_redis, sample_messages):
        """Test that set() uses custom stale_if_error_ttl."""
        custom_ttl = 7200

        await cache.set(
            model="claude-sonnet-4-5",
            messages=sample_messages,
            temperature=0.7,
            content="Hello!",
            provider="claude",
            input_tokens=10,
            output_tokens=5,
            stale_if_error_ttl=custom_ttl,
        )

        calls = mock_redis.setex.call_args_list
        fallback_call = calls[1]
        assert fallback_call[0][1] == custom_ttl

    @pytest.mark.asyncio
    async def test_get_fallback_returns_cached(self, cache, mock_redis, sample_messages):
        """Test get_fallback returns cached response."""
        cached_data = json.dumps(
            {
                "content": "Cached response",
                "model": "claude-sonnet-4-5",
                "provider": "claude",
                "input_tokens": 10,
                "output_tokens": 5,
                "finish_reason": "end_turn",
                "cached_at": "2026-01-06T00:00:00",
                "cache_key": "test-key",
            }
        )
        mock_redis.get = AsyncMock(return_value=cached_data)

        result = await cache.get_fallback(
            model="claude-sonnet-4-5",
            messages=sample_messages,
            temperature=0.7,
        )

        assert result is not None
        assert result.content == "Cached response"
        assert result.is_fallback is True

    @pytest.mark.asyncio
    async def test_get_fallback_uses_fallback_prefix(self, cache, mock_redis, sample_messages):
        """Test get_fallback looks in fallback cache."""
        mock_redis.get = AsyncMock(return_value=None)

        await cache.get_fallback(
            model="claude-sonnet-4-5",
            messages=sample_messages,
            temperature=0.7,
        )

        call_args = mock_redis.get.call_args[0][0]
        assert FALLBACK_PREFIX in call_args

    @pytest.mark.asyncio
    async def test_get_fallback_miss(self, cache, mock_redis, sample_messages):
        """Test get_fallback returns None on miss."""
        mock_redis.get = AsyncMock(return_value=None)

        result = await cache.get_fallback(
            model="claude-sonnet-4-5",
            messages=sample_messages,
            temperature=0.7,
        )

        assert result is None
        assert cache._stats.fallback_misses == 1

    @pytest.mark.asyncio
    async def test_get_fallback_updates_stats(self, cache, mock_redis, sample_messages):
        """Test get_fallback updates fallback stats."""
        cached_data = json.dumps(
            {
                "content": "Cached",
                "model": "claude-sonnet-4-5",
                "provider": "claude",
                "input_tokens": 10,
                "output_tokens": 5,
                "cached_at": "2026-01-06T00:00:00",
                "cache_key": "test-key",
            }
        )
        mock_redis.get = AsyncMock(return_value=cached_data)

        await cache.get_fallback(
            model="claude-sonnet-4-5",
            messages=sample_messages,
            temperature=0.7,
        )

        assert cache._stats.fallback_hits == 1
        assert cache.get_stats().fallback_usage == 1

    @pytest.mark.asyncio
    async def test_get_fallback_handles_redis_error(self, cache, mock_redis, sample_messages):
        """Test get_fallback handles Redis errors gracefully."""
        mock_redis.get = AsyncMock(side_effect=Exception("Redis connection error"))

        result = await cache.get_fallback(
            model="claude-sonnet-4-5",
            messages=sample_messages,
            temperature=0.7,
        )

        assert result is None
        assert cache._stats.fallback_misses == 1


class TestCacheFallbackIntegration:
    """Integration tests for cache fallback during outages."""

    @pytest.fixture
    def mock_redis(self):
        """Create mock Redis client with storage."""
        storage = {}

        async def mock_get(key):
            return storage.get(key)

        async def mock_setex(key, ttl, value):
            storage[key] = value

        mock = MagicMock()
        mock.get = mock_get
        mock.setex = mock_setex
        mock.close = AsyncMock()
        return mock, storage

    @pytest.mark.asyncio
    async def test_fallback_after_primary_expires(self, mock_redis):
        """Test fallback works when primary cache has expired."""
        mock_client, storage = mock_redis
        cache = ResponseCache()
        cache._client = mock_client

        messages = [{"role": "user", "content": "Test"}]

        await cache.set(
            model="claude-sonnet-4-5",
            messages=messages,
            temperature=0.7,
            content="Original response",
            provider="claude",
            input_tokens=10,
            output_tokens=5,
        )

        primary_key = cache._generate_cache_key("claude-sonnet-4-5", messages, 0.7)
        del storage[primary_key]

        primary_result = await cache.get(
            model="claude-sonnet-4-5",
            messages=messages,
            temperature=0.7,
        )
        assert primary_result is None

        fallback_result = await cache.get_fallback(
            model="claude-sonnet-4-5",
            messages=messages,
            temperature=0.7,
        )
        assert fallback_result is not None
        assert fallback_result.content == "Original response"
        assert fallback_result.is_fallback is True
