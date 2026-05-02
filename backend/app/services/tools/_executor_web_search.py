"""Search provider implementations for web search."""
from __future__ import annotations

import re
from typing import Any

import httpx

from app.config import settings

DEFAULT_SEARCH_REGION = "wt-wt"
DEFAULT_SEARXNG_TIMEOUT = 8.0
DEFAULT_SEARXNG_PORT = 18900
DEFAULT_USER_AGENT = (
    "agent-hub/1.0 (+http://localhost:3003; persona web research tool)"
)
_SEARXNG_TIMELIMITS = {
    "d": "day",
    "w": "week",
    "m": "month",
    "y": "year",
}


def _normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _normalize_search_result(index: int, raw: dict[str, Any]) -> dict[str, object] | None:
    url = str(raw.get("href") or raw.get("url") or "").strip()
    if not url:
        return None

    title = _normalize_whitespace(str(raw.get("title") or url))
    snippet = _normalize_whitespace(
        str(raw.get("body") or raw.get("excerpt") or raw.get("content") or "")
    )
    source = _normalize_whitespace(str(raw.get("source") or ""))
    search_engine = _normalize_whitespace(str(raw.get("engine") or ""))
    published = _normalize_whitespace(
        str(
            raw.get("date")
            or raw.get("published")
            or raw.get("published_at")
            or raw.get("publishedDate")
            or ""
        )
    )

    result: dict[str, object] = {"rank": index, "title": title, "url": url}
    if snippet:
        result["snippet"] = snippet
    if source:
        result["source"] = source
    if search_engine:
        result["search_engine"] = search_engine
    if published:
        result["published"] = published
    return result


def _get_searxng_base_url() -> str | None:
    configured = settings.web_search_searxng_url.strip()
    if configured:
        return configured.rstrip("/")
    host = settings.st_browser_host.strip()
    if not host:
        return None
    return f"http://{host}:{DEFAULT_SEARXNG_PORT}"


def _collect_unique_results(
    raw_results: list[Any], max_results: int, *, dict_only: bool = False
) -> list[dict[str, object]]:
    normalized: list[dict[str, object]] = []
    seen_urls: set[str] = set()
    for raw in raw_results:
        if dict_only and not isinstance(raw, dict):
            continue
        result = _normalize_search_result(len(normalized) + 1, raw)
        if result is None:
            continue
        url = str(result["url"])
        if url in seen_urls:
            continue
        seen_urls.add(url)
        normalized.append(result)
        if len(normalized) >= max_results:
            break
    return normalized


def _run_search_request(
    query: str,
    max_results: int,
    search_type: str,
    timelimit: str | None,
) -> list[dict[str, object]]:
    from ddgs import DDGS

    with DDGS() as ddgs:
        if search_type == "news":
            raw_results = ddgs.news(
                query,
                region=DEFAULT_SEARCH_REGION,
                safesearch="moderate",
                timelimit=timelimit,
                max_results=max_results,
            )
        else:
            raw_results = ddgs.text(
                query,
                region=DEFAULT_SEARCH_REGION,
                safesearch="moderate",
                timelimit=timelimit,
                max_results=max_results,
                backend="auto",
            )
        return _collect_unique_results(list(raw_results), max_results)


async def _search_with_searxng(
    base_url: str, *, query: str, max_results: int, search_type: str, timelimit: str | None,
) -> list[dict[str, object]]:
    params: dict[str, str | int] = {"q": query, "format": "json", "safesearch": 1}
    if search_type == "news":
        params["categories"] = "news"
    if timelimit:
        params["time_range"] = _SEARXNG_TIMELIMITS[timelimit]

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=DEFAULT_SEARXNG_TIMEOUT,
        headers={"User-Agent": DEFAULT_USER_AGENT, "Accept": "application/json"},
    ) as client:
        response = await client.get(f"{base_url}/search", params=params)
        response.raise_for_status()
        payload = response.json()

    raw_results = payload.get("results")
    if not isinstance(raw_results, list):
        raise ValueError("SearXNG response missing results list")
    return _collect_unique_results(raw_results, max_results, dict_only=True)
