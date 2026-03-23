"""Tests for web search and page fetch executors."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from app.services.tools._executor_web import fetch_web_page, search_web


class _FakeResponse:
    def __init__(
        self,
        *,
        text: str,
        url: str = "https://example.com/final",
        status_code: int = 200,
        content_type: str = "text/html; charset=utf-8",
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.text = text
        self.url = url
        self.status_code = status_code
        self.headers = {"content-type": content_type, **(extra_headers or {})}

    def raise_for_status(self) -> None:
        return None


class _FakeAsyncClient:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def get(self, url: str) -> _FakeResponse:
        assert url == "https://example.com"
        return self._response


class TestSearchWeb:
    @pytest.mark.asyncio
    async def test_returns_normalized_payload(self) -> None:
        with patch(
            "app.services.tools._executor_web._run_search_request",
            return_value=[
                {
                    "rank": 1,
                    "title": "Agent Hub",
                    "url": "https://example.com",
                    "snippet": "Research result",
                }
            ],
        ):
            result = await search_web("agent hub", max_results=3, search_type="text")

        payload = json.loads(result)
        assert payload["query"] == "agent hub"
        assert payload["result_count"] == 1
        assert payload["results"][0]["url"] == "https://example.com"

    @pytest.mark.asyncio
    async def test_rejects_invalid_timelimit(self) -> None:
        result = await search_web("agent hub", timelimit="bad")

        payload = json.loads(result)
        assert "timelimit" in payload["error"]


class TestFetchWebPage:
    @pytest.mark.asyncio
    async def test_returns_extracted_payload(self) -> None:
        response = _FakeResponse(
            text="<html><head><title>Ignored</title></head><body>hello</body></html>"
        )
        with (
            patch(
                "app.services.tools._executor_web.httpx.AsyncClient",
                return_value=_FakeAsyncClient(response),
            ),
            patch(
                "app.services.tools._executor_web._extract_markdown_payload",
                return_value=(
                    {
                        "title": "Example title",
                        "author": "Example author",
                        "date": "2026-03-23",
                        "sitename": "Example Site",
                    },
                    "# Heading\n\nBody text",
                ),
            ),
        ):
            result = await fetch_web_page("https://example.com", max_chars=5000)

        payload = json.loads(result)
        assert payload["title"] == "Example title"
        assert payload["author"] == "Example author"
        assert payload["site_name"] == "Example Site"
        assert payload["format"] == "markdown"
        assert payload["content"] == "# Heading\n\nBody text"
        assert payload["truncated"] is False

    @pytest.mark.asyncio
    async def test_prefers_direct_markdown_response_when_available(self) -> None:
        response = _FakeResponse(
            text="---\ntitle: Example\n---\n\n# Heading\n\nBody text",
            content_type="text/markdown; charset=utf-8",
            extra_headers={"x-markdown-tokens": "42"},
        )
        with (
            patch(
                "app.services.tools._executor_web.httpx.AsyncClient",
                return_value=_FakeAsyncClient(response),
            ),
            patch(
                "app.services.tools._executor_web._extract_markdown_payload",
            ) as mock_extract,
        ):
            result = await fetch_web_page("https://example.com", max_chars=5000)

        payload = json.loads(result)
        assert payload["format"] == "markdown"
        assert payload["content"] == "---\ntitle: Example\n---\n\n# Heading\n\nBody text"
        assert payload["markdown_tokens_estimate"] == 42
        mock_extract.assert_not_called()

    @pytest.mark.asyncio
    async def test_focus_query_returns_relevant_excerpt_for_large_content(self) -> None:
        response = _FakeResponse(
            text="<html><head><title>Ignored</title></head><body>hello</body></html>"
        )
        markdown = "\n\n".join(
            [
                "# Example page",
                "Release notes and changelog details for unrelated features.",
                "The extract endpoint returns markdown by default and accepts text as an option.",
                "Authentication uses a bearer token and the API is request-based.",
                "Completely unrelated footer details and community links.",
            ]
        )
        with (
            patch(
                "app.services.tools._executor_web.httpx.AsyncClient",
                return_value=_FakeAsyncClient(response),
            ),
            patch(
                "app.services.tools._executor_web._extract_markdown_payload",
                return_value=(
                    {
                        "title": "Example title",
                    },
                    markdown,
                ),
            ),
        ):
            result = await fetch_web_page(
                "https://example.com",
                max_chars=180,
                focus_query="extract endpoint markdown",
            )

        payload = json.loads(result)
        assert payload["focused"] is True
        assert payload["focus_strategy"] == "bm25_chunks"
        assert payload["focus_query"] == "extract endpoint markdown"
        assert "extract endpoint returns markdown" in payload["content"]
        assert "unrelated footer" not in payload["content"]

    @pytest.mark.asyncio
    async def test_rejects_non_http_url(self) -> None:
        result = await fetch_web_page("file:///tmp/test.txt")

        payload = json.loads(result)
        assert "http://" in payload["error"]
