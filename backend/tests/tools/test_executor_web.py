"""Tests for web search and page fetch executors."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.services.tools import _executor_web
from app.services.tools._executor_web import fetch_web_page, research_web, search_web


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


class _FailingResponse(_FakeResponse):
    def raise_for_status(self) -> None:
        request = httpx.Request("GET", self.url)
        response = httpx.Response(self.status_code, request=request)
        raise httpx.HTTPStatusError("boom", request=request, response=response)


class _FakeAsyncClient:
    def __init__(self, response: _FakeResponse, *, expected_url: str = "https://example.com") -> None:
        self._response = response
        self._expected_url = expected_url

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def get(self, url: str) -> _FakeResponse:
        assert url == self._expected_url
        return self._response


class TestSearchWeb:
    @pytest.mark.asyncio
    async def test_returns_normalized_payload(self) -> None:
        with (
            patch("app.services.tools._executor_web._get_searxng_base_url", return_value=None),
            patch(
                "app.services.tools._executor_web._run_search_request",
                return_value=[
                    {
                        "rank": 1,
                        "title": "Agent Hub",
                        "url": "https://example.com",
                        "snippet": "Research result",
                    }
                ],
            ),
        ):
            result = await search_web("agent hub", max_results=3, search_type="text")

        payload = json.loads(result)
        assert payload["query"] == "agent hub"
        assert payload["result_count"] == 1
        assert payload["results"][0]["url"] == "https://example.com"
        assert payload["provider"] == "ddgs"

    @pytest.mark.asyncio
    async def test_rejects_invalid_timelimit(self) -> None:
        result = await search_web("agent hub", timelimit="bad")

        payload = json.loads(result)
        assert "timelimit" in payload["error"]

    @pytest.mark.asyncio
    async def test_prefers_searxng_when_configured(self) -> None:
        with (
            patch.object(_executor_web.settings, "web_search_searxng_url", "http://vm100:18900"),
            patch(
                "app.services.tools._executor_web._search_with_searxng",
                return_value=[
                    {
                        "rank": 1,
                        "title": "React docs",
                        "url": "https://react.dev/reference/react/useEffectEvent",
                    }
                ],
            ) as mock_searxng,
            patch("app.services.tools._executor_web._run_search_request") as mock_ddgs,
        ):
            result = await search_web("react useEffectEvent", max_results=3)

        payload = json.loads(result)
        assert payload["provider"] == "searxng"
        assert payload["results"][0]["url"] == "https://react.dev/reference/react/useEffectEvent"
        mock_searxng.assert_awaited_once_with(
            "http://vm100:18900",
            query="react useEffectEvent",
            max_results=3,
            search_type="text",
            timelimit=None,
        )
        mock_ddgs.assert_not_called()

    @pytest.mark.asyncio
    async def test_falls_back_to_ddgs_when_searxng_fails(self) -> None:
        with (
            patch.object(_executor_web.settings, "web_search_searxng_url", "http://vm100:18900"),
            patch(
                "app.services.tools._executor_web._search_with_searxng",
                side_effect=RuntimeError("searxng unavailable"),
            ) as mock_searxng,
            patch(
                "app.services.tools._executor_web._run_search_request",
                return_value=[
                    {
                        "rank": 1,
                        "title": "Fallback result",
                        "url": "https://example.com/fallback",
                    }
                ],
            ) as mock_ddgs,
        ):
            result = await search_web("agent hub", max_results=2)

        payload = json.loads(result)
        assert payload["provider"] == "ddgs"
        assert payload["provider_errors"] == [
            {
                "provider": "searxng",
                "detail": "searxng unavailable",
            }
        ]
        mock_searxng.assert_awaited_once()
        mock_ddgs.assert_called_once()


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
        assert payload["fetch_backend"] == "direct"
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
        assert payload["fetch_backend"] == "direct"
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
    async def test_focus_query_can_window_into_long_unbroken_content(self) -> None:
        markdown = (
            " ".join(f"prefix{i}" for i in range(180))
            + " Pompeian robust olive oil price $38.79 package 68 fl oz unit $0.57/fl oz. "
            + " ".join(f"suffix{i}" for i in range(180))
        )
        response = _FakeResponse(
            text=markdown,
            content_type="text/markdown; charset=utf-8",
        )
        with patch(
            "app.services.tools._executor_web.httpx.AsyncClient",
            return_value=_FakeAsyncClient(response),
        ):
            result = await fetch_web_page(
                "https://example.com",
                max_chars=180,
                focus_query="olive oil price 68 fl oz unit",
            )

        payload = json.loads(result)
        assert payload["focused"] is True
        assert payload["focus_strategy"] == "bm25_term_window"
        assert "$38.79" in payload["content"]
        assert "$0.57/fl oz" in payload["content"]
        assert "prefix0" not in payload["content"]
        assert len(payload["content"]) <= 180

    @pytest.mark.asyncio
    async def test_can_use_jina_reader_backend_explicitly(self) -> None:
        response = _FakeResponse(
            text="# Example page\n\nOlive oil costs $38.79 for 68 fl oz.",
            url="https://r.jina.ai/https://example.com",
            content_type="text/plain; charset=utf-8",
        )
        with patch(
            "app.services.tools._executor_web.httpx.AsyncClient",
            return_value=_FakeAsyncClient(
                response,
                expected_url="https://r.jina.ai/https://example.com",
            ),
        ):
            result = await fetch_web_page(
                "https://example.com",
                max_chars=5000,
                focus_query="olive oil price fl oz",
                backend="jina",
            )

        payload = json.loads(result)
        assert payload["fetch_backend"] == "jina"
        assert payload["site_name"] == "Jina Reader"
        assert payload["reader_url"] == "https://r.jina.ai/https://example.com"
        assert "68 fl oz" in payload["content"]

    @pytest.mark.asyncio
    async def test_auto_backend_falls_back_to_jina_when_direct_request_fails(self) -> None:
        direct_client = _FakeAsyncClient(
            _FailingResponse(text="", status_code=503),
        )
        jina_client = _FakeAsyncClient(
            _FakeResponse(
                text="# Jina fallback\n\nRecovered markdown content.",
                url="https://r.jina.ai/https://example.com",
                content_type="text/plain; charset=utf-8",
            ),
            expected_url="https://r.jina.ai/https://example.com",
        )
        with patch(
            "app.services.tools._executor_web.httpx.AsyncClient",
            side_effect=[direct_client, jina_client],
        ):
            result = await fetch_web_page("https://example.com", max_chars=5000)

        payload = json.loads(result)
        assert payload["fetch_backend"] == "jina"
        assert payload["fallback_reason"].startswith("direct request failed:")
        assert "Recovered markdown content" in payload["content"]

    @pytest.mark.asyncio
    async def test_auto_backend_uses_jina_for_sparse_dynamic_shell_without_browser(self) -> None:
        shell_html = (
            "<!doctype html><html><head><title>Shell</title>"
            "<script>window.__APP__ = true;</script></head>"
            "<body><main id='app'></main></body></html>"
            + (" " * 1000)
        )
        direct_page = SimpleNamespace(
            content="Shell",
            format="text",
            title="Shell",
            site_name=None,
            author=None,
            published=None,
            markdown_tokens_estimate=None,
        )
        direct_client = _FakeAsyncClient(_FakeResponse(text=shell_html))
        jina_client = _FakeAsyncClient(
            _FakeResponse(
                text="# Rendered page\n\nLoaded dynamic price data.",
                url="https://r.jina.ai/https://example.com",
                content_type="text/plain; charset=utf-8",
            ),
            expected_url="https://r.jina.ai/https://example.com",
        )

        with (
            patch.object(_executor_web.settings, "web_fetch_browser_cdp_url", ""),
            patch.object(_executor_web.settings, "st_browser_host", ""),
            patch(
                "app.services.tools._executor_web.httpx.AsyncClient",
                side_effect=[direct_client, jina_client],
            ),
            patch(
                "app.services.tools._executor_web._extract_page_content",
                return_value=direct_page,
            ),
        ):
            result = await fetch_web_page("https://example.com", max_chars=5000)

        payload = json.loads(result)
        assert payload["fetch_backend"] == "jina"
        assert payload["fallback_reason"] == "direct extraction looked like a sparse dynamic shell"
        assert "Loaded dynamic price data" in payload["content"]

    @pytest.mark.asyncio
    async def test_rejects_unknown_fetch_backend(self) -> None:
        result = await fetch_web_page("https://example.com", backend="unknown")

        payload = json.loads(result)
        assert "backend must be one of" in payload["error"]
        assert payload["backend"] == "unknown"

    @pytest.mark.asyncio
    async def test_uses_browser_fallback_for_sparse_html_pages(self) -> None:
        response = _FakeResponse(
            text=(
                "<!doctype html><html><head><title>Shell</title>"
                "<script>setTimeout(() => { const target = document.getElementById('late-content'); "
                "target.textContent = 'Loaded dynamic content with actual pricing.'; }, 1200);</script>"
                "</head><body><main><h1>Shell</h1><p>Starts mostly empty.</p>"
                "<div id='late-content'></div></main></body></html>"
            )
        )
        direct_page = SimpleNamespace(
            content="Shell",
            format="text",
            title="Shell",
            site_name=None,
            author=None,
            published=None,
            markdown_tokens_estimate=None,
        )
        browser_page = SimpleNamespace(
            content="# Browser title\n\nLoaded dynamic content with actual pricing.",
            format="markdown",
            title="Browser title",
            site_name=None,
            author=None,
            published=None,
            markdown_tokens_estimate=None,
        )

        with (
            patch.object(_executor_web.settings, "web_fetch_browser_cdp_url", "http://vm100:9222"),
            patch(
                "app.services.tools._executor_web.httpx.AsyncClient",
                return_value=_FakeAsyncClient(response),
            ),
            patch(
                "app.services.tools._executor_web._extract_page_content",
                side_effect=[direct_page, browser_page],
            ) as mock_extract,
            patch(
                "app.services.tools._executor_web._render_html_via_browser",
                new_callable=AsyncMock,
                return_value=(
                    "https://example.com/browser",
                    "<html><body><main><h1>Browser title</h1><p>Loaded dynamic content with actual pricing.</p></main></body></html>",
                ),
            ) as mock_render,
        ):
            result = await fetch_web_page("https://example.com", max_chars=5000)

        payload = json.loads(result)
        assert payload["fetch_backend"] == "browser"
        assert payload["final_url"] == "https://example.com/browser"
        assert payload["title"] == "Browser title"
        assert "Loaded dynamic content" in payload["content"]
        assert mock_extract.call_count == 2
        mock_render.assert_awaited_once_with(
            "https://example.com",
            "http://vm100:9222",
        )

    @pytest.mark.asyncio
    async def test_rejects_non_http_url(self) -> None:
        result = await fetch_web_page("file:///tmp/test.txt")

        payload = json.loads(result)
        assert "http://" in payload["error"]


class TestResearchWeb:
    @pytest.mark.asyncio
    async def test_returns_search_and_page_payload(self) -> None:
        with (
            patch(
                "app.services.tools._executor_web.search_web",
                new_callable=AsyncMock,
                return_value=json.dumps(
                    {
                        "query": "Cloudflare Markdown for Agents",
                        "provider": "searxng",
                        "result_count": 1,
                        "results": [
                            {
                                "rank": 1,
                                "title": "Markdown for Agents",
                                "url": "https://blog.cloudflare.com/markdown-for-agents/",
                            }
                        ],
                    }
                ),
            ) as mock_search,
            patch(
                "app.services.tools._executor_web.fetch_web_page",
                new_callable=AsyncMock,
                return_value=json.dumps(
                    {
                        "url": "https://blog.cloudflare.com/markdown-for-agents/",
                        "final_url": "https://blog.cloudflare.com/markdown-for-agents/",
                        "fetch_backend": "direct",
                        "format": "markdown",
                        "content": "# Markdown for Agents\n\nAgent-friendly markdown output.",
                    }
                ),
            ) as mock_fetch,
        ):
            result = await research_web("Cloudflare Markdown for Agents")

        payload = json.loads(result)
        assert payload["query"] == "Cloudflare Markdown for Agents"
        assert payload["selected_result"]["rank"] == 1
        assert payload["selected_result"]["url"] == "https://blog.cloudflare.com/markdown-for-agents/"
        assert payload["focus_query"] == "Cloudflare Markdown for Agents"
        assert payload["page"]["fetch_backend"] == "direct"
        mock_search.assert_awaited_once_with(
            query="Cloudflare Markdown for Agents",
            max_results=5,
            search_type="text",
            timelimit=None,
        )
        mock_fetch.assert_awaited_once_with(
            url="https://blog.cloudflare.com/markdown-for-agents/",
            max_chars=12000,
            focus_query="Cloudflare Markdown for Agents",
            backend="auto",
        )

    @pytest.mark.asyncio
    async def test_returns_unfetched_payload_when_search_has_no_results(self) -> None:
        with patch(
            "app.services.tools._executor_web.search_web",
            new_callable=AsyncMock,
            return_value=json.dumps(
                {
                    "query": "no matches",
                    "provider": "searxng",
                    "result_count": 0,
                    "results": [],
                }
            ),
        ) as mock_search:
            result = await research_web("no matches")

        payload = json.loads(result)
        assert payload["query"] == "no matches"
        assert payload["fetched"] is False
        assert payload["selected_result"] is None
        assert payload["message"] == "No search results to fetch."
        mock_search.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_surfaces_fetch_step_failure_with_search_context(self) -> None:
        with (
            patch(
                "app.services.tools._executor_web.search_web",
                new_callable=AsyncMock,
                return_value=json.dumps(
                    {
                        "query": "Cloudflare Markdown for Agents",
                        "provider": "searxng",
                        "result_count": 1,
                        "results": [
                            {
                                "rank": 1,
                                "title": "Markdown for Agents",
                                "url": "https://blog.cloudflare.com/markdown-for-agents/",
                            }
                        ],
                    }
                ),
            ),
            patch(
                "app.services.tools._executor_web.fetch_web_page",
                new_callable=AsyncMock,
                return_value=json.dumps(
                    {
                        "error": "fetch_web_page request failed",
                        "url": "https://blog.cloudflare.com/markdown-for-agents/",
                    }
                ),
            ),
        ):
            result = await research_web("Cloudflare Markdown for Agents")

        payload = json.loads(result)
        assert payload["error"] == "research_web fetch step failed"
        assert payload["selected_result"]["rank"] == 1
        assert payload["page"]["error"] == "fetch_web_page request failed"
