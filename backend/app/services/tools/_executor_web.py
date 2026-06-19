"""Web search and page-fetch tool executors."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx

from app.config import settings  # noqa: F401 — used by tests via _executor_web.settings

from ._executor_web_focus import _select_focused_content
from ._executor_web_html import (
    _browser_result_is_better,
    _build_fetch_payload,
    _extract_markdown_payload,
    _extract_title_from_html,
    _fallback_html_text,
    _get_browser_cdp_url,
    _PageExtraction,
    _render_html_via_browser,
    _should_try_browser_fallback,
)
from ._executor_web_search import (
    _get_searxng_base_url,
    _run_search_request,
    _search_with_searxng,
)

DEFAULT_WEB_SEARCH_RESULTS = 5
MAX_WEB_SEARCH_RESULTS = 10
DEFAULT_WEB_FETCH_MAX_CHARS = 12000
MAX_WEB_FETCH_MAX_CHARS = 50000
DEFAULT_FETCH_TIMEOUT = 20.0
DEFAULT_FETCH_ACCEPT = (
    "text/markdown, text/html;q=0.9, application/xhtml+xml;q=0.8, "
    "text/plain;q=0.7, application/json;q=0.5, */*;q=0.1"
)
DEFAULT_USER_AGENT = (
    "agent-hub/1.0 (+http://localhost:3003; persona web research tool)"
)
JINA_READER_BASE_URL = "https://r.jina.ai"
_SEARCH_TYPES = frozenset({"text", "news"})
_TIMELIMITS = frozenset({"d", "w", "m", "y"})
_FETCH_BACKENDS = frozenset({"auto", "direct", "jina"})

logger = logging.getLogger(__name__)


def _json_payload(payload: dict[str, object]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)


def _error_payload(message: str, **extra: object) -> str:
    return _json_payload({"error": message, **extra})


def _decode_payload(payload: str, *, source: str) -> dict[str, Any]:
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{source} returned invalid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{source} returned a non-object JSON payload")
    return parsed


def _normalize_whitespace(value: str) -> str:
    import re
    return re.sub(r"\s+", " ", value).strip()


def _truncate_text(text: str, max_chars: int) -> tuple[str, bool]:
    cleaned = text.strip()
    if len(cleaned) <= max_chars:
        return cleaned, False
    return cleaned[: max_chars - 1].rstrip() + "…", True


def _extract_page_content(
    content_type: str,
    raw_text: str,
    final_url: str,
    markdown_tokens_estimate: str | None = None,
) -> _PageExtraction:
    title: str | None = None
    site_name: str | None = None
    author: str | None = None
    published: str | None = None
    content_format = "text"
    parsed_markdown_tokens: int | None = None

    if "markdown" in content_type:
        content = raw_text.strip()
        content_format = "markdown"
    elif "html" in content_type or not content_type:
        metadata, markdown = _extract_markdown_payload(raw_text, final_url)
        title = metadata.get("title") or _extract_title_from_html(raw_text)
        site_name = metadata.get("sitename") or metadata.get("site_name")
        author = metadata.get("author")
        published = metadata.get("date")
        extracted_text = markdown or metadata.get("raw_text") or metadata.get("text") or ""
        content = markdown if markdown else _normalize_whitespace(str(extracted_text))
        if not content:
            content = _fallback_html_text(raw_text)
        content_format = "markdown" if markdown else "text"
    elif content_type.startswith("text/") or "json" in content_type:
        content = raw_text
    else:
        raise ValueError("unsupported content type")

    if markdown_tokens_estimate and markdown_tokens_estimate.isdigit():
        parsed_markdown_tokens = int(markdown_tokens_estimate)

    return _PageExtraction(
        content=content,
        format=content_format,
        title=title,
        site_name=site_name,
        author=author,
        published=published,
        markdown_tokens_estimate=parsed_markdown_tokens,
    )


def _validate_search_args(query: str, search_type: str, timelimit: str | None) -> str | None:
    if not query:
        return _error_payload("search_web requires a non-empty query")
    if search_type not in _SEARCH_TYPES:
        return _error_payload("search_web search_type must be one of: text, news", search_type=search_type)
    if timelimit is not None and timelimit not in _TIMELIMITS:
        return _error_payload("search_web timelimit must be one of: d, w, m, y", timelimit=timelimit)
    return None


def _decode_step(raw: str, source: str, step_name: str) -> tuple[dict[str, Any], str | None]:
    """Decode a JSON step result; returns (payload, None) or ({}, error_json)."""
    try:
        return _decode_payload(raw, source=source), None
    except ValueError as exc:
        return {}, _error_payload(
            f"research_web could not decode {step_name} payload", detail=str(exc)
        )


def _pick_search_result(
    search_payload: dict[str, Any],
    normalized_query: str,
    result_index: int,
) -> tuple[dict[str, object] | None, str | None, str | None]:
    """Returns (selected_result, url, None) or (None, None, error_json)."""
    raw_results = search_payload.get("results")
    if not isinstance(raw_results, list):
        return None, None, _error_payload(
            "research_web search step returned an invalid results payload",
            query=normalized_query,
        )
    if not raw_results:
        return None, None, _json_payload({
            "query": normalized_query,
            "search": search_payload,
            "selected_result": None,
            "fetched": False,
            "message": "No search results to fetch.",
        })
    if result_index > len(raw_results):
        return None, None, _error_payload(
            "research_web result_index exceeds available search results",
            query=normalized_query,
            result_index=result_index,
            available_results=len(raw_results),
        )
    selected = raw_results[result_index - 1]
    if not isinstance(selected, dict):
        return None, None, _error_payload(
            "research_web selected result is malformed",
            query=normalized_query,
            result_index=result_index,
        )
    url = str(selected.get("url") or "").strip()
    if not url:
        return None, None, _error_payload(
            "research_web selected result is missing a URL",
            query=normalized_query,
            result_index=result_index,
        )
    return selected, url, None


async def _try_browser_fallback(
    normalized_url: str,
    browser_cdp_url: str,
    content_type: str,
    raw_text: str,
    page: _PageExtraction,
    original_final_url: str,
) -> tuple[_PageExtraction, str, str]:
    """Try browser rendering; returns (page, final_url, fetch_backend)."""
    if not _should_try_browser_fallback(content_type, raw_text, page.content):
        return page, original_final_url, "direct"
    try:
        b_url, b_html = await _render_html_via_browser(normalized_url, browser_cdp_url)
        b_page = await asyncio.to_thread(
            _extract_page_content, "text/html; charset=utf-8", b_html, b_url,
        )
        if _browser_result_is_better(page.content, b_page.content):
            return b_page, b_url, "browser"
    except Exception as exc:
        logger.warning("fetch_web_page browser fallback failed for %r: %s", normalized_url, exc)
    return page, original_final_url, "direct"


def _apply_focus_and_truncation(
    page: _PageExtraction,
    *,
    max_chars: int,
    focus_query: str | None,
) -> tuple[str, bool, str, dict[str, object], str | None]:
    nfocus = _normalize_whitespace(focus_query or "")
    content_out, focus_meta = _select_focused_content(page.content, nfocus or None, max_chars)
    content_out = content_out if focus_meta.get("focused") else page.content
    trunc_content, truncated = _truncate_text(content_out, max_chars)
    excerpt, _ = _truncate_text(_normalize_whitespace(trunc_content.replace("\n", " ")), min(500, max_chars))
    return trunc_content, truncated, excerpt, focus_meta, nfocus or None


async def _fetch_with_jina_reader(
    normalized_url: str,
    *,
    max_chars: int,
    focus_query: str | None,
    fallback_reason: str | None = None,
) -> str:
    reader_url = f"{JINA_READER_BASE_URL}/{normalized_url}"
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=DEFAULT_FETCH_TIMEOUT,
            headers={"User-Agent": DEFAULT_USER_AGENT, "Accept": "text/plain, text/markdown;q=0.9"},
        ) as client:
            response = await client.get(reader_url)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("fetch_web_page Jina Reader failed for %r: %s", normalized_url, exc)
        return _error_payload(
            "fetch_web_page jina request failed",
            detail=str(exc),
            fallback_reason=fallback_reason,
            reader_url=reader_url,
            url=normalized_url,
        )

    page = _PageExtraction(
        content=response.text.strip(),
        format="markdown",
        title=None,
        site_name="Jina Reader",
    )
    trunc_content, truncated, excerpt, focus_meta, nfocus = _apply_focus_and_truncation(
        page,
        max_chars=max_chars,
        focus_query=focus_query,
    )
    payload = _build_fetch_payload(
        page,
        response.status_code,
        "jina",
        normalized_url,
        str(response.url),
        response.headers.get("content-type", "text/plain"),
        nfocus,
        focus_meta,
        trunc_content,
        truncated,
        excerpt,
    )
    payload["reader_url"] = reader_url
    if fallback_reason:
        payload["fallback_reason"] = fallback_reason
    return _json_payload(payload)


async def search_web(
    query: str,
    max_results: int = DEFAULT_WEB_SEARCH_RESULTS,
    search_type: str = "text",
    timelimit: str | None = None,
) -> str:
    """Search the public web and return normalized result metadata."""
    normalized_query = query.strip()
    if err := _validate_search_args(normalized_query, search_type, timelimit):
        return err

    bounded = max(1, min(max_results, MAX_WEB_SEARCH_RESULTS))
    provider, provider_errors, results = "ddgs", [], []

    searxng_url = _get_searxng_base_url()
    if searxng_url:
        try:
            results = await _search_with_searxng(
                searxng_url, query=normalized_query, max_results=bounded,
                search_type=search_type, timelimit=timelimit,
            )
            if results:
                provider = "searxng"
        except Exception as exc:
            logger.warning("search_web searxng failed for %r: %s", normalized_query, exc)
            provider_errors.append({"provider": "searxng", "detail": str(exc)})

    if not results:
        try:
            results = await asyncio.to_thread(
                _run_search_request, normalized_query, bounded, search_type, timelimit,
            )
        except Exception as exc:
            logger.warning("search_web failed for %r: %s", normalized_query, exc)
            err_d: dict[str, object] = {"detail": str(exc), "query": normalized_query}
            if provider_errors:
                err_d["provider_errors"] = provider_errors
            return _error_payload("search_web request failed", **err_d)

    payload: dict[str, object] = {
        "provider": provider, "query": normalized_query,
        "result_count": len(results), "results": results, "search_type": search_type,
    }
    if provider_errors:
        payload["provider_errors"] = provider_errors
    if timelimit:
        payload["timelimit"] = timelimit
    return _json_payload(payload)


async def fetch_web_page(
    url: str,
    max_chars: int = DEFAULT_WEB_FETCH_MAX_CHARS,
    focus_query: str | None = None,
    backend: str = "auto",
) -> str:
    """Fetch a webpage and return extracted readable content."""
    normalized_url = url.strip()
    if not normalized_url:
        return _error_payload("fetch_web_page requires a non-empty url")
    if not normalized_url.startswith(("http://", "https://")):
        return _error_payload("fetch_web_page only supports http:// and https:// URLs")
    backend = (backend or "auto").strip().lower()
    if backend not in _FETCH_BACKENDS:
        return _error_payload(
            "fetch_web_page backend must be one of: auto, direct, jina",
            backend=backend,
        )

    bounded_max_chars = max(100, min(max_chars, MAX_WEB_FETCH_MAX_CHARS))
    if backend == "jina":
        return await _fetch_with_jina_reader(
            normalized_url,
            max_chars=bounded_max_chars,
            focus_query=focus_query,
        )

    try:
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=DEFAULT_FETCH_TIMEOUT,
            headers={"User-Agent": DEFAULT_USER_AGENT, "Accept": DEFAULT_FETCH_ACCEPT},
        ) as client:
            response = await client.get(normalized_url)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("fetch_web_page failed for %r: %s", normalized_url, exc)
        if backend == "auto":
            return await _fetch_with_jina_reader(
                normalized_url,
                max_chars=bounded_max_chars,
                focus_query=focus_query,
                fallback_reason=f"direct request failed: {exc}",
            )
        return _error_payload("fetch_web_page request failed", detail=str(exc), url=normalized_url)

    content_type = response.headers.get("content-type", "").lower()
    final_url, raw_text = str(response.url), response.text
    try:
        page = await asyncio.to_thread(
            _extract_page_content, content_type, raw_text, final_url, response.headers.get("x-markdown-tokens"),
        )
    except ValueError:
        if backend == "auto":
            return await _fetch_with_jina_reader(
                normalized_url,
                max_chars=bounded_max_chars,
                focus_query=focus_query,
                fallback_reason=f"unsupported content type: {content_type}",
            )
        return _error_payload("fetch_web_page only supports text-like responses", content_type=content_type, url=normalized_url)

    browser_cdp_url = _get_browser_cdp_url()
    if browser_cdp_url:
        page, final_url, fetch_backend = await _try_browser_fallback(
            normalized_url, browser_cdp_url, content_type, raw_text, page, final_url,
        )
    else:
        fetch_backend = "direct"
    if (
        backend == "auto"
        and fetch_backend == "direct"
        and _should_try_browser_fallback(content_type, raw_text, page.content)
    ):
        jina_raw = await _fetch_with_jina_reader(
            normalized_url,
            max_chars=bounded_max_chars,
            focus_query=focus_query,
            fallback_reason="direct extraction looked like a sparse dynamic shell",
        )
        jina_payload = json.loads(jina_raw)
        if "error" not in jina_payload:
            return jina_raw
    trunc_content, truncated, excerpt, focus_meta, nfocus = _apply_focus_and_truncation(
        page,
        max_chars=bounded_max_chars,
        focus_query=focus_query,
    )

    return _json_payload(_build_fetch_payload(
        page, response.status_code, fetch_backend, normalized_url, final_url,
        content_type, nfocus, focus_meta, trunc_content, truncated, excerpt,
    ))


async def research_web(
    query: str,
    max_results: int = DEFAULT_WEB_SEARCH_RESULTS,
    result_index: int = 1,
    search_type: str = "text",
    timelimit: str | None = None,
    max_chars: int = DEFAULT_WEB_FETCH_MAX_CHARS,
    focus_query: str | None = None,
    backend: str = "auto",
) -> str:
    """Search the web, choose one result, and fetch readable content."""
    normalized_query = _normalize_whitespace(query)
    if not normalized_query:
        return _error_payload("research_web requires a non-empty query")
    if result_index < 1:
        return _error_payload("research_web result_index must be at least 1", result_index=result_index)

    search_raw = await search_web(query=normalized_query, max_results=max_results, search_type=search_type, timelimit=timelimit)
    search_payload, err = _decode_step(search_raw, "search_web", "search step")
    if err:
        return err
    if "error" in search_payload:
        return _json_payload({"error": "research_web search step failed", "query": normalized_query, "search": search_payload})

    selected_result, selected_url, err = _pick_search_result(search_payload, normalized_query, result_index)
    if err:
        return err

    effective_focus = _normalize_whitespace(focus_query or normalized_query)
    page_raw = await fetch_web_page(
        url=selected_url,
        max_chars=max_chars,
        focus_query=effective_focus,
        backend=backend,
    )
    page_payload, err = _decode_step(page_raw, "fetch_web_page", "fetch step")
    if err:
        return err
    if "error" in page_payload:
        return _json_payload({
            "error": "research_web fetch step failed",
            "focus_query": effective_focus,
            "page": page_payload,
            "query": normalized_query,
            "search": search_payload,
            "selected_result": selected_result,
        })

    return _json_payload({
        "fetched": True,
        "focus_query": effective_focus,
        "page": page_payload,
        "query": normalized_query,
        "search": search_payload,
        "selected_result": selected_result,
    })


__all__ = [
    "DEFAULT_WEB_FETCH_MAX_CHARS",
    "DEFAULT_WEB_SEARCH_RESULTS",
    "MAX_WEB_FETCH_MAX_CHARS",
    "MAX_WEB_SEARCH_RESULTS",
    "fetch_web_page",
    "research_web",
    "search_web",
]
