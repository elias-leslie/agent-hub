"""Memory operations for Agent Hub clients."""

from typing import Any

from agent_hub._utils import handle_error


class MemoryOperationsMixin:
    """Mixin providing memory operations methods."""

    def rate_episode(
        self,
        uuid: str,
        rating: str,
    ) -> dict[str, Any]:
        """Rate a memory episode for ACE-aligned feedback.

        Args:
            uuid: Episode UUID to rate.
            rating: Rating type ("helpful", "harmful", or "used").

        Returns:
            Dict with success status and message.
        """
        client = self._get_client()
        payload = {"rating": rating}
        headers = self._inject_tracking_headers("sdk.rate_episode")
        response = client.post(
            f"/api/memory/episodes/{uuid}/rating",
            json=payload,
            headers=headers,
        )
        if not response.is_success:
            handle_error(response)
        return response.json()

    def save_learning(
        self,
        content: str,
        *,
        injection_tier: str = "reference",
        confidence: int = 80,
        context: str | None = None,
        scope: str = "global",
        scope_id: str | None = None,
        summary: str | None = None,
    ) -> dict[str, Any]:
        """Save a learning to the memory system.

        Args:
            content: The learning content to save.
            injection_tier: Tier for injection priority ("mandate", "guardrail", "reference").
            confidence: Confidence level 0-100 (70+ provisional, 90+ canonical).
            context: Optional context about the learning source.
            scope: Memory scope ("global" or "project").
            scope_id: Scope identifier (e.g., project ID) when scope is "project".

        Returns:
            Dict with uuid, status, is_duplicate, reinforced_uuid, and message.
        """
        client = self._get_client()
        payload: dict[str, Any] = {
            "content": content,
            "injection_tier": injection_tier,
            "confidence": confidence,
        }
        if context:
            payload["context"] = context
        if summary:
            payload["summary"] = summary

        headers = self._inject_tracking_headers("sdk.save_learning")
        headers = self._build_memory_headers(headers, scope, scope_id)
        response = client.post(
            "/api/memory/save-learning", json=payload, headers=headers
        )
        if not response.is_success:
            handle_error(response)
        return response.json()

    def list_episodes(
        self,
        *,
        limit: int = 50,
        cursor: str | None = None,
        category: str | None = None,
        scope: str = "global",
        scope_id: str | None = None,
    ) -> dict[str, Any]:
        """List memory episodes with cursor-based pagination.

        Args:
            limit: Max episodes per page (1-100).
            cursor: Timestamp cursor for pagination.
            category: Filter by injection tier ("mandate", "guardrail", "reference").
            scope: Memory scope ("global" or "project").
            scope_id: Scope identifier when scope is "project".

        Returns:
            Dict with episodes list, total count, cursor, and has_more flag.
        """
        client = self._get_client()
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        if category:
            params["category"] = category

        headers = self._inject_tracking_headers("sdk.list_episodes")
        headers = self._build_memory_headers(headers, scope, scope_id)
        response = client.get("/api/memory/list", params=params, headers=headers)
        if not response.is_success:
            handle_error(response)
        return response.json()

    def search_memories(
        self,
        query: str,
        *,
        limit: int = 10,
        min_score: float = 0.0,
        scope: str = "global",
        scope_id: str | None = None,
    ) -> dict[str, Any]:
        """Search memory for relevant episodes and facts.

        Args:
            query: Search query.
            limit: Max results (1-100).
            min_score: Minimum relevance score (0.0-1.0).
            scope: Memory scope ("global" or "project").
            scope_id: Scope identifier when scope is "project".

        Returns:
            Dict with query, results list, and count.
        """
        client = self._get_client()
        params: dict[str, Any] = {
            "query": query,
            "limit": limit,
            "min_score": min_score,
        }
        headers = self._inject_tracking_headers("sdk.search_memories")
        headers = self._build_memory_headers(headers, scope, scope_id)
        response = client.get("/api/memory/search", params=params, headers=headers)
        if not response.is_success:
            handle_error(response)
        return response.json()

    def get_memory_stats(
        self,
        *,
        scope: str = "global",
        scope_id: str | None = None,
    ) -> dict[str, Any]:
        """Get memory statistics for the current group.

        Args:
            scope: Memory scope ("global" or "project").
            scope_id: Scope identifier when scope is "project".

        Returns:
            Dict with total, by_category list, by_scope list, last_updated, scope, and scope_id.
        """
        client = self._get_client()
        headers = self._inject_tracking_headers("sdk.get_memory_stats")
        headers = self._build_memory_headers(headers, scope, scope_id)
        response = client.get("/api/memory/stats", headers=headers)
        if not response.is_success:
            handle_error(response)
        return response.json()


class AsyncMemoryOperationsMixin:
    """Mixin providing async memory operations methods."""

    async def rate_episode(
        self,
        uuid: str,
        rating: str,
    ) -> dict[str, Any]:
        """Rate a memory episode for ACE-aligned feedback asynchronously."""
        client = await self._get_client()
        payload = {"rating": rating}
        headers = self._inject_tracking_headers("sdk.rate_episode")
        response = await client.post(
            f"/api/memory/episodes/{uuid}/rating",
            json=payload,
            headers=headers,
        )
        if not response.is_success:
            handle_error(response)
        return response.json()

    async def save_learning(
        self,
        content: str,
        *,
        injection_tier: str = "reference",
        confidence: int = 80,
        context: str | None = None,
        scope: str = "global",
        scope_id: str | None = None,
        summary: str | None = None,
    ) -> dict[str, Any]:
        """Save a learning to the memory system asynchronously."""
        client = await self._get_client()
        payload: dict[str, Any] = {
            "content": content,
            "injection_tier": injection_tier,
            "confidence": confidence,
        }
        if context:
            payload["context"] = context
        if summary:
            payload["summary"] = summary

        headers = self._inject_tracking_headers("sdk.save_learning")
        headers = self._build_memory_headers(headers, scope, scope_id)
        response = await client.post(
            "/api/memory/save-learning", json=payload, headers=headers
        )
        if not response.is_success:
            handle_error(response)
        return response.json()

    async def list_episodes(
        self,
        *,
        limit: int = 50,
        cursor: str | None = None,
        category: str | None = None,
        scope: str = "global",
        scope_id: str | None = None,
    ) -> dict[str, Any]:
        """List memory episodes with cursor-based pagination asynchronously."""
        client = await self._get_client()
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        if category:
            params["category"] = category

        headers = self._inject_tracking_headers("sdk.list_episodes")
        headers = self._build_memory_headers(headers, scope, scope_id)
        response = await client.get("/api/memory/list", params=params, headers=headers)
        if not response.is_success:
            handle_error(response)
        return response.json()

    async def search_memories(
        self,
        query: str,
        *,
        limit: int = 10,
        min_score: float = 0.0,
        scope: str = "global",
        scope_id: str | None = None,
    ) -> dict[str, Any]:
        """Search memory for relevant episodes and facts asynchronously."""
        client = await self._get_client()
        params: dict[str, Any] = {
            "query": query,
            "limit": limit,
            "min_score": min_score,
        }
        headers = self._inject_tracking_headers("sdk.search_memories")
        headers = self._build_memory_headers(headers, scope, scope_id)
        response = await client.get(
            "/api/memory/search", params=params, headers=headers
        )
        if not response.is_success:
            handle_error(response)
        return response.json()

    async def get_memory_stats(
        self,
        *,
        scope: str = "global",
        scope_id: str | None = None,
    ) -> dict[str, Any]:
        """Get memory statistics for the current group asynchronously."""
        client = await self._get_client()
        headers = self._inject_tracking_headers("sdk.get_memory_stats")
        headers = self._build_memory_headers(headers, scope, scope_id)
        response = await client.get("/api/memory/stats", headers=headers)
        if not response.is_success:
            handle_error(response)
        return response.json()
