"""Web search and page-fetch tool executors."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from html import unescape
from html.parser import HTMLParser
from typing import Any, cast

import httpx

DEFAULT_WEB_SEARCH_RESULTS = 5
MAX_WEB_SEARCH_RESULTS = 10
DEFAULT_WEB_FETCH_MAX_CHARS = 12000
MAX_WEB_FETCH_MAX_CHARS = 50000
DEFAULT_SEARCH_REGION = "wt-wt"
DEFAULT_FETCH_TIMEOUT = 20.0
DEFAULT_FETCH_ACCEPT = (
    "text/markdown, text/html;q=0.9, application/xhtml+xml;q=0.8, "
    "text/plain;q=0.7, application/json;q=0.5, */*;q=0.1"
)
DEFAULT_USER_AGENT = (
    "agent-hub/1.0 (+http://localhost:3003; Jenny web research tool)"
)

_SEARCH_TYPES = frozenset({"text", "news"})
_TIMELIMITS = frozenset({"d", "w", "m", "y"})

logger = logging.getLogger(__name__)


def _json_payload(payload: dict[str, object]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)


def _error_payload(message: str, **extra: object) -> str:
    return _json_payload({"error": message, **extra})


def _normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


class _HTMLTextExtractor(HTMLParser):
    """Minimal HTML-to-text fallback when article extraction fails."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {"script", "style", "noscript"}:
            self._ignored_depth += 1
            return
        if self._ignored_depth == 0 and tag in {"p", "br", "div", "li", "section", "article"}:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._ignored_depth > 0:
            self._ignored_depth -= 1
            return
        if self._ignored_depth == 0 and tag in {"p", "div", "li", "section", "article"}:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignored_depth == 0 and data.strip():
            self._parts.append(data)

    def text(self) -> str:
        return _normalize_whitespace(unescape(" ".join(self._parts)))


def _fallback_html_text(html: str) -> str:
    parser = _HTMLTextExtractor()
    parser.feed(html)
    parser.close()
    return parser.text()


def _extract_title_from_html(html: str) -> str | None:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    title = _normalize_whitespace(unescape(match.group(1)))
    return title or None


def _truncate_text(text: str, max_chars: int) -> tuple[str, bool]:
    cleaned = text.strip()
    if len(cleaned) <= max_chars:
        return cleaned, False
    return cleaned[: max_chars - 1].rstrip() + "…", True


def _tokenize_focus_text(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9_]+", text.lower())


def _split_long_block(block: str, max_chars: int) -> list[str]:
    if len(block) <= max_chars:
        return [block]

    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", block)
        if sentence.strip()
    ]
    if len(sentences) <= 1:
        return [block[i : i + max_chars].strip() for i in range(0, len(block), max_chars)]

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for sentence in sentences:
        sentence_len = len(sentence) + (1 if current else 0)
        if current and current_len + sentence_len > max_chars:
            chunks.append(" ".join(current).strip())
            current = [sentence]
            current_len = len(sentence)
            continue
        current.append(sentence)
        current_len += sentence_len
    if current:
        chunks.append(" ".join(current).strip())
    return chunks


def _build_focus_chunks(content: str) -> list[tuple[int, str]]:
    raw_blocks = [block.strip() for block in re.split(r"\n\s*\n+", content) if block.strip()]
    if not raw_blocks:
        normalized = content.strip()
        return [(0, normalized)] if normalized else []

    chunks: list[str] = []
    index = 0
    while index < len(raw_blocks):
        block = raw_blocks[index]
        if index + 1 < len(raw_blocks) and len(block) <= 120 and (
            block.startswith("#") or "\n" not in block
        ):
            block = f"{block}\n\n{raw_blocks[index + 1]}"
            index += 2
        else:
            index += 1
        chunks.extend(_split_long_block(block, max_chars=1200))

    return [(chunk_index, chunk) for chunk_index, chunk in enumerate(chunks) if chunk.strip()]


def _select_focused_content(
    content: str,
    focus_query: str | None,
    max_chars: int,
) -> tuple[str, dict[str, object]]:
    normalized_query = _normalize_whitespace(focus_query or "")
    stripped_content = content.strip()
    if not normalized_query or not stripped_content:
        return content, {"focused": False}

    chunks = _build_focus_chunks(stripped_content)
    if not chunks:
        return content, {"focused": False}

    query_terms = _tokenize_focus_text(normalized_query)
    if not query_terms:
        return content, {"focused": False}

    from rank_bm25 import BM25Okapi

    chunk_terms = [_tokenize_focus_text(chunk) for _, chunk in chunks]
    if not any(chunk_terms):
        return content, {"focused": False}

    scores = BM25Okapi(chunk_terms).get_scores(query_terms)
    ranked_indices = sorted(range(len(chunks)), key=lambda idx: scores[idx], reverse=True)

    selected_indices: list[int] = []
    selected_chars = 0
    for idx in ranked_indices:
        score = float(scores[idx])
        chunk_text = chunks[idx][1]
        if not chunk_text.strip():
            continue
        if score <= 0:
            continue
        projected = selected_chars + len(chunk_text) + (2 if selected_indices else 0)
        if selected_indices and projected > max_chars:
            continue
        selected_indices.append(idx)
        selected_chars = projected
        if selected_chars >= max_chars:
            break

    if not selected_indices:
        return content, {"focused": False}

    selected_indices.sort(key=lambda idx: chunks[idx][0])
    focused_content = "\n\n".join(chunks[idx][1] for idx in selected_indices).strip()
    if not focused_content:
        return content, {"focused": False}

    return focused_content, {
        "focused": focused_content != stripped_content,
        "focus_query": normalized_query,
        "focus_strategy": "bm25_chunks",
        "selected_chunk_count": len(selected_indices),
        "candidate_chunk_count": len(chunks),
    }


def _normalize_search_result(index: int, raw: dict[str, Any]) -> dict[str, object] | None:
    url = str(raw.get("href") or raw.get("url") or "").strip()
    if not url:
        return None

    title = _normalize_whitespace(str(raw.get("title") or url))
    snippet = _normalize_whitespace(str(raw.get("body") or raw.get("excerpt") or ""))
    source = _normalize_whitespace(str(raw.get("source") or ""))
    published = _normalize_whitespace(
        str(raw.get("date") or raw.get("published") or raw.get("published_at") or "")
    )

    result: dict[str, object] = {
        "rank": index,
        "title": title,
        "url": url,
    }
    if snippet:
        result["snippet"] = snippet
    if source:
        result["source"] = source
    if published:
        result["published"] = published
    return result


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

        normalized: list[dict[str, object]] = []
        seen_urls: set[str] = set()
        for raw in raw_results:
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


async def search_web(
    query: str,
    max_results: int = DEFAULT_WEB_SEARCH_RESULTS,
    search_type: str = "text",
    timelimit: str | None = None,
) -> str:
    """Search the public web and return normalized result metadata."""
    normalized_query = query.strip()
    if not normalized_query:
        return _error_payload("search_web requires a non-empty query")
    if search_type not in _SEARCH_TYPES:
        return _error_payload(
            "search_web search_type must be one of: text, news",
            search_type=search_type,
        )
    if timelimit is not None and timelimit not in _TIMELIMITS:
        return _error_payload(
            "search_web timelimit must be one of: d, w, m, y",
            timelimit=timelimit,
        )

    bounded_max_results = max(1, min(max_results, MAX_WEB_SEARCH_RESULTS))
    try:
        results = await asyncio.to_thread(
            _run_search_request,
            normalized_query,
            bounded_max_results,
            search_type,
            timelimit,
        )
    except Exception as exc:
        logger.warning("search_web failed for %r: %s", normalized_query, exc)
        return _error_payload(
            "search_web request failed",
            detail=str(exc),
            query=normalized_query,
        )

    payload: dict[str, object] = {
        "query": normalized_query,
        "result_count": len(results),
        "results": results,
        "search_type": search_type,
    }
    if timelimit:
        payload["timelimit"] = timelimit
    return _json_payload(payload)


def _extract_markdown_payload(html: str, url: str) -> tuple[dict[str, Any], str]:
    import trafilatura

    metadata_obj = trafilatura.bare_extraction(
        html,
        url=url,
        favor_recall=True,
        include_links=True,
        include_tables=True,
        include_formatting=True,
        with_metadata=True,
    )
    metadata: dict[str, Any] = {}
    if metadata_obj is not None:
        as_dict = getattr(metadata_obj, "as_dict", None)
        if callable(as_dict):
            metadata = as_dict()
        elif isinstance(metadata_obj, dict):
            metadata = cast(dict[str, Any], metadata_obj)

    markdown = trafilatura.extract(
        html,
        url=url,
        favor_recall=True,
        include_links=True,
        include_tables=True,
        include_formatting=True,
        output_format="markdown",
    ) or ""
    return metadata, markdown.strip()


async def fetch_web_page(
    url: str,
    max_chars: int = DEFAULT_WEB_FETCH_MAX_CHARS,
    focus_query: str | None = None,
) -> str:
    """Fetch a webpage and return extracted readable content."""
    normalized_url = url.strip()
    if not normalized_url:
        return _error_payload("fetch_web_page requires a non-empty url")
    if not normalized_url.startswith(("http://", "https://")):
        return _error_payload("fetch_web_page only supports http:// and https:// URLs")

    bounded_max_chars = max(100, min(max_chars, MAX_WEB_FETCH_MAX_CHARS))
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": DEFAULT_FETCH_ACCEPT,
    }

    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=DEFAULT_FETCH_TIMEOUT,
            headers=headers,
        ) as client:
            response = await client.get(normalized_url)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("fetch_web_page failed for %r: %s", normalized_url, exc)
        return _error_payload(
            "fetch_web_page request failed",
            detail=str(exc),
            url=normalized_url,
        )

    content_type = response.headers.get("content-type", "").lower()
    final_url = str(response.url)
    raw_text = response.text
    title: str | None = None
    site_name: str | None = None
    author: str | None = None
    published: str | None = None
    content_format = "text"
    markdown_tokens_estimate = response.headers.get("x-markdown-tokens")

    if "markdown" in content_type:
        content = raw_text.strip()
        content_format = "markdown"
    elif "html" in content_type or not content_type:
        metadata, markdown = await asyncio.to_thread(
            _extract_markdown_payload,
            raw_text,
            final_url,
        )
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
        return _error_payload(
            "fetch_web_page only supports text-like responses",
            content_type=content_type,
            url=normalized_url,
        )

    focused_content, focus_metadata = _select_focused_content(
        content,
        focus_query,
        bounded_max_chars,
    )
    content_for_payload = focused_content if focus_metadata.get("focused") else content

    truncated_content, truncated = _truncate_text(content_for_payload, bounded_max_chars)
    excerpt, _ = _truncate_text(
        _normalize_whitespace(truncated_content.replace("\n", " ")),
        min(500, bounded_max_chars),
    )

    payload: dict[str, object] = {
        "content": truncated_content,
        "content_type": content_type or "unknown",
        "final_url": final_url,
        "format": content_format,
        "status_code": response.status_code,
        "truncated": truncated,
        "url": normalized_url,
    }
    if title:
        payload["title"] = title
    if site_name:
        payload["site_name"] = site_name
    if author:
        payload["author"] = author
    if published:
        payload["published"] = published
    if excerpt:
        payload["excerpt"] = excerpt
    if markdown_tokens_estimate and markdown_tokens_estimate.isdigit():
        payload["markdown_tokens_estimate"] = int(markdown_tokens_estimate)
    if focus_query:
        payload["focus_query"] = _normalize_whitespace(focus_query)
    if focus_metadata.get("focused"):
        payload["focused"] = True
        payload["focus_strategy"] = focus_metadata["focus_strategy"]
        payload["selected_chunk_count"] = focus_metadata["selected_chunk_count"]
        payload["candidate_chunk_count"] = focus_metadata["candidate_chunk_count"]
    elif focus_query:
        payload["focused"] = False

    return _json_payload(payload)


__all__ = [
    "DEFAULT_WEB_FETCH_MAX_CHARS",
    "DEFAULT_WEB_SEARCH_RESULTS",
    "MAX_WEB_FETCH_MAX_CHARS",
    "MAX_WEB_SEARCH_RESULTS",
    "fetch_web_page",
    "search_web",
]
