"""HTML extraction, page content parsing, and browser rendering for web fetch."""
from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from typing import Any, cast

from app.config import settings

DEFAULT_FETCH_TIMEOUT = 20.0
DEFAULT_BROWSER_RENDER_WAIT_MS = 2500
DEFAULT_BROWSER_CDP_PORT = 9222
_SPARSE_CONTENT_CHARS = 400
_SPA_SHELL_MARKERS = (
    'id="__next"',
    "id='__next'",
    'id="root"',
    "id='root'",
    'id="app"',
    "id='app'",
    "data-reactroot",
    "ng-version",
    'id="___gatsby"',
    "__NUXT__",
)
_EMPTY_DYNAMIC_CONTAINER_RE = re.compile(
    r"<(div|main|section|article)[^>]+(?:id|class)=['\"][^'\"]+['\"][^>]*>\s*</(?:div|main|section|article)>"
)


def _normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


@dataclass(slots=True)
class _PageExtraction:
    content: str
    format: str
    title: str | None = None
    site_name: str | None = None
    author: str | None = None
    published: str | None = None
    published_date_inferred: bool = False
    markdown_tokens_estimate: int | None = None


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


def _structured_article_markdown(html: str) -> str:
    """Keep the relationships between headings, conditions, lists and table cells."""
    from lxml import html as lxml_html

    try:
        root = lxml_html.fromstring(html)
        candidates = root.xpath("//article | //main") or root.xpath('//*[@role="main"]')
        if not candidates:
            return ""
        article = max(candidates, key=lambda node: len(node.text_content().strip()))
        for node in article.xpath(".//script | .//style | .//nav | .//footer | .//aside | .//form"):
            node.drop_tree()
    except (ValueError, TypeError):
        return ""

    blocks: list[str] = []

    def visit(node: Any) -> None:
        tag = str(node.tag).lower()
        value = _normalize_whitespace(node.text_content())
        if not value:
            return
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            blocks.append(f"{'#' * int(tag[1])} {value.removesuffix('¶').rstrip()}")
            return
        if tag == "pre":
            blocks.append(f"```\n{node.text_content().strip()}\n```")
            return
        if tag == "table":
            rows = []
            for row in node.xpath(".//tr"):
                cells = [_normalize_whitespace(cell.text_content()) for cell in row.xpath("./th | ./td")]
                if cells:
                    rows.append("| " + " | ".join(cells) + " |")
            if rows:
                blocks.append("\n".join(rows))
            return
        if tag in {"ul", "ol"}:
            items = [_normalize_whitespace(item.text_content()) for item in node.xpath("./li")]
            if items:
                blocks.append("\n".join(f"- {item}" for item in items if item))
            return
        if tag in {"p", "blockquote"}:
            blocks.append(value)
            return
        for child in node:
            visit(child)

    visit(article)
    return "\n\n".join(blocks).strip()


def _extract_markdown_payload(html: str, url: str) -> tuple[dict[str, Any], str]:
    import trafilatura
    from trafilatura.core import determine_returnstring
    from trafilatura.settings import Extractor

    options = Extractor(
        output_format="markdown", recall=True, links=True, tables=True,
        formatting=True, url=url, with_metadata=True,
    )
    document = trafilatura.bare_extraction(
        html,
        options=options,
    )
    metadata: dict[str, Any] = {}
    if document is not None:
        as_dict = getattr(document, "as_dict", None)
        if callable(as_dict):
            metadata = as_dict()
        elif isinstance(document, dict):
            metadata = cast(dict[str, Any], document)
    markdown = determine_returnstring(document, options) if document is not None and not isinstance(document, dict) else ""
    markdown = re.sub(r"^---\n.*?\n---\n", "", markdown, count=1, flags=re.DOTALL)
    structured = _structured_article_markdown(html)
    if structured and len(structured) >= len(markdown.strip()) * 0.6:
        markdown = structured
    return metadata, markdown.strip()


def _should_try_browser_fallback(
    content_type: str,
    raw_html: str,
    content: str,
) -> bool:
    if "html" not in content_type and content_type:
        return False
    stripped_content = content.strip()
    lowered_html = raw_html.lower()
    if len(stripped_content) < _SPARSE_CONTENT_CHARS:
        if len(raw_html) >= 1000:
            return True
        if "<script" in lowered_html and _EMPTY_DYNAMIC_CONTAINER_RE.search(lowered_html):
            return True
    return len(stripped_content) < (_SPARSE_CONTENT_CHARS * 3) and any(
        marker.lower() in lowered_html for marker in _SPA_SHELL_MARKERS
    )


def _browser_result_is_better(direct_content: str, browser_content: str) -> bool:
    direct_len = len(direct_content.strip())
    browser_len = len(browser_content.strip())
    if browser_len <= direct_len:
        return False
    if direct_len < _SPARSE_CONTENT_CHARS:
        return browser_len >= direct_len + 40
    return browser_len >= int(direct_len * 1.25)


async def _render_html_via_browser(url: str, browser_cdp_url: str) -> tuple[str, str]:
    from playwright.async_api import async_playwright

    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(browser_cdp_url)
        try:
            page = await browser.new_page()
            try:
                await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=int(DEFAULT_FETCH_TIMEOUT * 1000),
                )
                await page.wait_for_timeout(DEFAULT_BROWSER_RENDER_WAIT_MS)
                rendered_html = await page.content()
                return page.url, rendered_html
            finally:
                await page.close()
        finally:
            await browser.close()


def _get_browser_cdp_url() -> str | None:
    configured = settings.web_fetch_browser_cdp_url.strip()
    if configured:
        return configured
    host = settings.st_browser_host.strip()
    if not host:
        return None
    return f"http://{host}:{DEFAULT_BROWSER_CDP_PORT}"


def _build_fetch_payload(
    page: _PageExtraction,
    response_status: int,
    fetch_backend: str,
    normalized_url: str,
    final_url: str,
    content_type: str,
    focus_query: str | None,
    focus_metadata: dict[str, object],
    truncated_content: str,
    truncated: bool,
    excerpt: str,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "content": truncated_content,
        "content_type": content_type or "unknown",
        "fetch_backend": fetch_backend,
        "final_url": final_url,
        "format": page.format,
        "status_code": response_status,
        "truncated": truncated,
        "url": normalized_url,
    }
    if page.title:
        payload["title"] = page.title
    if page.site_name:
        payload["site_name"] = page.site_name
    if page.author:
        payload["author"] = page.author
    if page.published:
        payload["published"] = page.published
        payload["published_date_inferred"] = page.published_date_inferred
    if excerpt:
        payload["excerpt"] = excerpt
    if page.markdown_tokens_estimate is not None:
        payload["markdown_tokens_estimate"] = page.markdown_tokens_estimate
    if focus_query:
        payload["focus_query"] = focus_query
    if focus_metadata.get("focused"):
        payload["focused"] = True
        payload["focus_strategy"] = focus_metadata["focus_strategy"]
        payload["selected_chunk_count"] = focus_metadata["selected_chunk_count"]
        payload["candidate_chunk_count"] = focus_metadata["candidate_chunk_count"]
    elif focus_query:
        payload["focused"] = False
    payload["content_complete"] = bool(truncated_content) and not truncated and not focus_metadata.get("focused")
    if not payload["content_complete"]:
        payload["incomplete_reason"] = (
            "focus_selection" if focus_metadata.get("focused") else
            "character_limit" if truncated else "empty_extraction"
        )
    return payload
