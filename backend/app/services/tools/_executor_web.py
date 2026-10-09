"""Web search and page-fetch tool executors."""
from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import math
import time
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import httpx

from app.config import settings  # noqa: F401 — used by tests via _executor_web.settings

from ._executor_web_artifacts import load_artifact, save_artifact
from ._executor_web_focus import _normalize_whitespace, _select_focused_content
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
from ._executor_web_lightpanda import fetch_lightpanda
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
_FETCH_BACKENDS = frozenset({"auto", "direct", "jina", "lightpanda"})
_SENSITIVE_QUERY_MARKERS = ("token", "credential", "api_key", "apikey", "password", "secret", "signature", "sig", "auth", "key", "code")

logger = logging.getLogger(__name__)


class _UnsupportedContentType(ValueError):
    """The response MIME is unsupported, distinct from extraction failure."""


def _retain_full_content(payload: dict[str, Any], content: str, *, max_chars: int = DEFAULT_WEB_FETCH_MAX_CHARS) -> str:
    payload.setdefault("coverage", {"scope": "document", "source_completeness": "unverified"})
    payload["coverage"]["full_extraction_retained"] = True
    try:
        payload.update(save_artifact(payload, content))
    except OSError as exc:
        payload["artifact_error"] = str(exc)
        payload["coverage"]["full_extraction_retained"] = False
        payload.setdefault("stages", []).append({"stage": "artifact_write", "error": str(exc)})
    else:
        payload["coverage"]["full_extraction_retained"] = True
    diagnostic_truncated: list[str] = []

    def bound_diagnostics(value: Any, prefix: str = "") -> None:
        if isinstance(value, dict):
            for key, item in list(value.items()):
                path = f"{prefix}.{key}" if prefix else key
                if key in {"raw_receipt", "stderr", "detail"} and isinstance(item, str) and len(item) > max_chars:
                    value[key], _ = _truncate_text(item, max_chars)
                    diagnostic_truncated.append(path)
                else:
                    bound_diagnostics(item, path)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                bound_diagnostics(item, f"{prefix}[{index}]")

    # Save exact evidence first; the response contains bounded diagnostic previews.
    bound_diagnostics(payload)
    if diagnostic_truncated:
        payload["diagnostic_truncated"] = diagnostic_truncated
        payload["diagnostic_artifact_available"] = bool(payload.get("artifact_id"))
    return _json_payload(payload)


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


def _truncate_text(text: str, max_chars: int) -> tuple[str, bool]:
    cleaned = text.strip()
    if len(cleaned) <= max_chars:
        return cleaned, False
    return cleaned[: max_chars - 1].rstrip() + "…", True


def _public_fallback_allowed(url: str) -> bool:
    """A public reader must not receive local addresses or URL credentials."""
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").rstrip(".").lower()
        if parsed.scheme not in {"http", "https"} or not host or parsed.username or parsed.password:
            return False
        if "." not in host or host == "localhost" or host.endswith((
            ".localhost", ".local", ".internal", ".test", ".lan", ".home", ".corp", ".intranet", ".invalid",
        )):
            return False
        try:
            if not ipaddress.ip_address(host).is_global:
                return False
        except ValueError:
            pass
        if any(
            any(marker in key.lower() for marker in _SENSITIVE_QUERY_MARKERS)
            for key, _ in parse_qsl(parsed.query, keep_blank_values=True)
        ):
            return False
        return not parsed.fragment
    except ValueError:
        return False


def _explicit_published_date(html: str) -> bool:
    import re
    return bool(re.search(
        r'<meta\b(?=[^>]*(?:article:published_time|datePublished|pubdate))(?=[^>]*\bcontent\s*=)[^>]*>|<time\s+[^>]*datetime\s*=',
        html, re.IGNORECASE,
    ))


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
        raise _UnsupportedContentType("unsupported content type")

    if markdown_tokens_estimate and markdown_tokens_estimate.isdigit():
        parsed_markdown_tokens = int(markdown_tokens_estimate)

    return _PageExtraction(
        content=content,
        format=content_format,
        title=title,
        site_name=site_name,
        author=author,
        published=published,
        published_date_inferred=bool(published) and not _explicit_published_date(raw_text),
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
    stages: list[dict[str, object]] | None = None,
) -> tuple[_PageExtraction, str, str]:
    """Try browser rendering; returns (page, final_url, fetch_backend)."""
    if not _should_try_browser_fallback(content_type, raw_text, page.content):
        return page, original_final_url, "direct"
    started = time.monotonic()
    stage: dict[str, object] = {"stage": "browser_fallback"}
    try:
        b_url, b_html = await _render_html_via_browser(normalized_url, browser_cdp_url)
        b_page = await asyncio.to_thread(
            _extract_page_content, "text/html; charset=utf-8", b_html, b_url,
        )
        if _browser_result_is_better(page.content, b_page.content):
            stage["selected"] = True
            return b_page, b_url, "browser"
        stage["selected"] = False
    except Exception as exc:
        stage["error"] = str(exc)
        logger.warning("fetch_web_page browser fallback failed for %r: %s", normalized_url, exc)
    finally:
        stage["duration_ms"] = round((time.monotonic() - started) * 1000, 3)
        if stages is not None:
            stages.append(stage)
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
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_FETCH_TIMEOUT,
    stages: list[dict[str, object]] | None = None,
    prior_failure: dict[str, Any] | None = None,
) -> str:
    if not _public_fallback_allowed(normalized_url):
        return _error_payload("fetch_web_page public reader rejects private or credential-bearing URL")
    reader_url = f"{JINA_READER_BASE_URL}/{normalized_url}"
    started = time.monotonic()
    try:
        if client is not None:
            response = await client.get(reader_url, timeout=timeout, headers={"Accept": "text/plain, text/markdown;q=0.9"})
            response.raise_for_status()
        else:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=timeout,
                headers={"User-Agent": DEFAULT_USER_AGENT, "Accept": "text/plain, text/markdown;q=0.9"},
            ) as reader_client:
                response = await reader_client.get(reader_url)
                response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("fetch_web_page Jina Reader failed for %r: %s", normalized_url, exc)
        return _error_payload(
            "fetch_web_page jina request failed",
            detail=str(exc),
            fallback_reason=fallback_reason,
            reader_url=reader_url,
            url=normalized_url,
            stages=(stages or []) + [{"stage": "jina_request", "duration_ms": round((time.monotonic() - started) * 1000, 3), "error": str(exc)}],
            direct_failure=prior_failure,
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
    payload["stages"] = (stages or []) + [{"stage": "jina_request", "duration_ms": round((time.monotonic() - started) * 1000, 3)}]
    if prior_failure:
        payload["direct_failure"] = prior_failure
    if fallback_reason:
        payload["fallback_reason"] = fallback_reason
    return _retain_full_content(payload, page.content, max_chars=max_chars)


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
    payload["status"] = "results" if results else "no_results"
    if timelimit:
        payload["timelimit"] = timelimit
    return _json_payload(payload)


async def fetch_web_page(
    url: str,
    max_chars: int = DEFAULT_WEB_FETCH_MAX_CHARS,
    focus_query: str | None = None,
    backend: str = "auto",
    selector: str | None = None,
    wait_script: str | None = None,
    timeout: float = DEFAULT_FETCH_TIMEOUT,
    *,
    _client: httpx.AsyncClient | None = None,
) -> str:
    """Fetch through the shared extraction seam; retain the full extracted artifact."""
    started = time.monotonic()
    normalized_url = url.strip()
    if not normalized_url:
        return _error_payload("fetch_web_page requires a non-empty url")
    if not normalized_url.startswith(("http://", "https://")):
        return _error_payload("fetch_web_page only supports http:// and https:// URLs")
    backend = (backend or "auto").strip().lower()
    if backend not in _FETCH_BACKENDS:
        return _error_payload("fetch_web_page backend must be one of: auto, direct, jina, lightpanda", backend=backend)
    if not math.isfinite(timeout) or timeout <= 0:
        return _error_payload("fetch_web_page timeout must be finite and positive")
    if backend != "lightpanda" and (selector or wait_script):
        return _error_payload("selector and wait_script require backend lightpanda")
    bounded = max(100, min(max_chars, MAX_WEB_FETCH_MAX_CHARS))
    stages: list[dict[str, object]] = []

    async def reader(reason: str | None = None, target_url: str | None = None, prior_failure: dict[str, Any] | None = None) -> str:
        raw = await _fetch_with_jina_reader(
            target_url or normalized_url, max_chars=bounded, focus_query=focus_query,
            fallback_reason=reason, client=_client,
            timeout=timeout,
            stages=stages, prior_failure=prior_failure,
        )
        result = json.loads(raw)
        result.setdefault("stages", stages)
        result["total_ms"] = round((time.monotonic() - started) * 1000, 3)
        return _json_payload(result)

    if backend == "jina":
        return await reader()
    if backend == "lightpanda":
        receipt = await fetch_lightpanda(normalized_url, selector=selector, wait_script=wait_script, timeout=timeout)
        content = str(receipt.get("content") or "")
        page = _PageExtraction(content=content, format="markdown")
        out, truncated, excerpt, focus_meta, nfocus = _apply_focus_and_truncation(page, max_chars=bounded, focus_query=focus_query)
        payload = _build_fetch_payload(page, receipt.get("http_status", 0), "lightpanda", normalized_url,
                                       str(receipt.get("url") or normalized_url), "text/markdown", nfocus,
                                       focus_meta, out, truncated, excerpt)
        payload["lightpanda"] = receipt.get("lightpanda", receipt)
        payload["stages"] = [
            {"stage": "lightpanda_verification", "duration_ms": payload["lightpanda"].get("verification_ms", 0)},
            {"stage": "lightpanda_fetch", "duration_ms": receipt.get("fetch_ms", 0), "error": receipt.get("error")},
        ]
        payload["coverage"] = {"scope": "selector" if selector else "document", "selector": selector,
                               "readiness": "predicate_passed" if wait_script and not receipt.get("error") else "domcontentloaded" if not receipt.get("error") else "failed",
                               "source_completeness": "unverified", "visual_rendering": False,
                               "omitted_resources": ["images", "stylesheets", "workers", "iframes"]}
        payload["content_complete"] = False
        payload["incomplete_reason"] = "source_completeness_unverified"
        if receipt.get("error"):
            payload.update(error=receipt["error"], detail=receipt.get("detail", receipt.get("stderr", "")),
                           process_exit_code=receipt.get("process_exit_code"))
            payload["incomplete_reason"] = "backend_failure"
            payload["recovery"] = "Retry with direct or jina for readable text; use a managed Chrome browser for visual or interaction evidence. Those routes do not verify this readiness predicate."
            payload["backend_failure"] = {key: value for key, value in receipt.items() if key != "content"}
        payload["total_ms"] = round((time.monotonic() - started) * 1000, 3)
        return _retain_full_content(payload, content, max_chars=bounded)

    request_started = time.monotonic()
    try:
        if _client is not None:
            response = await _client.get(normalized_url, timeout=timeout)
            response.raise_for_status()
        else:
            async with httpx.AsyncClient(
                follow_redirects=True, timeout=timeout,
                headers={"User-Agent": DEFAULT_USER_AGENT, "Accept": DEFAULT_FETCH_ACCEPT},
            ) as client:
                response = await client.get(normalized_url)
                response.raise_for_status()
    except httpx.HTTPError as exc:
        stages.append({"stage": "direct_request", "error": str(exc), "duration_ms": round((time.monotonic() - request_started) * 1000, 3)})
        if backend == "auto":
            return await reader("direct request failed: provider returned an error")
        return _error_payload("fetch_web_page request failed", detail=str(exc), url=normalized_url, stages=stages)
    stages.append({"stage": "direct_request", "duration_ms": round((time.monotonic() - request_started) * 1000, 3)})
    content_type = response.headers.get("content-type", "").lower()
    final_url, raw_text = str(response.url), response.text
    extraction_started = time.monotonic()
    try:
        page = await asyncio.to_thread(_extract_page_content, content_type, raw_text, final_url, response.headers.get("x-markdown-tokens"))
    except Exception as exc:
        unsupported = isinstance(exc, _UnsupportedContentType)
        stages.append({"stage": "direct_extraction", "error": str(exc), "duration_ms": round((time.monotonic() - extraction_started) * 1000, 3)})
        error = "fetch_web_page only supports text-like responses" if unsupported else "fetch_web_page extraction failed"
        failure = {"error": error, "detail": str(exc), "content_type": content_type, "url": normalized_url,
                   "stages": stages, "artifact_kind": "raw_response", "content_complete": False}
        # Keep the response evidence even if auto's public reader succeeds.
        failure = json.loads(_retain_full_content(failure, raw_text, max_chars=bounded))
        if backend == "auto":
            return await reader(f"{'unsupported content type' if unsupported else 'direct extraction failed'}: {content_type}", prior_failure=failure)
        return _json_payload(failure)
    stages.append({"stage": "direct_extraction", "duration_ms": round((time.monotonic() - extraction_started) * 1000, 3)})
    browser_cdp_url = _get_browser_cdp_url() if backend == "auto" else None
    if browser_cdp_url:
        page, final_url, fetch_backend = await _try_browser_fallback(normalized_url, browser_cdp_url, content_type, raw_text, page, final_url, stages)
    else:
        fetch_backend = "direct"
    fallback_failure = None
    sparse = _should_try_browser_fallback(content_type, raw_text, page.content)
    if backend == "auto" and fetch_backend == "direct" and sparse:
        jina_raw = await reader("direct extraction looked like a sparse dynamic shell",
                                final_url if _public_fallback_allowed(normalized_url) else normalized_url)
        jina_payload = json.loads(jina_raw)
        if "error" not in jina_payload:
            return jina_raw
        fallback_failure = jina_payload
    out, truncated, excerpt, focus_meta, nfocus = _apply_focus_and_truncation(page, max_chars=bounded, focus_query=focus_query)
    payload = _build_fetch_payload(page, response.status_code, fetch_backend, normalized_url, final_url,
                                   content_type, nfocus, focus_meta, out, truncated, excerpt)
    payload["stages"] = stages
    payload["total_ms"] = round((time.monotonic() - started) * 1000, 3)
    payload["coverage"] = {"scope": "document", "source_completeness": "unverified",
                           "sparse_dynamic_shell": sparse, "full_extraction_retained": True}
    if fallback_failure:
        payload["fallback_failure"] = fallback_failure
    if fetch_backend == "direct" and sparse:
        payload["content_complete"] = False
        payload["incomplete_reason"] = "sparse_dynamic_shell"
    return _retain_full_content(payload, page.content, max_chars=bounded)


def refocus_web_artifact(artifact: str, *, max_chars: int = DEFAULT_WEB_FETCH_MAX_CHARS, focus_query: str | None = None) -> str:
    """Produce another bounded view from a trusted retained extraction, without network."""
    try:
        record = load_artifact(artifact)
    except ValueError as exc:
        return _error_payload("web artifact refocus failed", detail=str(exc))
    if record.get("artifact_kind") == "raw_response":
        return _error_payload("web artifact contains a failed raw response, not extracted content", artifact_id=record["artifact_id"])
    page = _PageExtraction(content=record["content"], format=record.get("format", "text"),
        title=record.get("title"), site_name=record.get("site_name"), author=record.get("author"),
        published=record.get("published"), published_date_inferred=record.get("published_date_inferred", False),
        markdown_tokens_estimate=record.get("markdown_tokens_estimate"))
    out, truncated, excerpt, focus_meta, nfocus = _apply_focus_and_truncation(
        page, max_chars=max(100, min(max_chars, MAX_WEB_FETCH_MAX_CHARS)), focus_query=focus_query,
    )
    payload = _build_fetch_payload(page, record.get("status_code", 0), record.get("fetch_backend", "unknown"),
        record.get("url", ""), record.get("final_url", ""), record.get("content_type", ""),
        nfocus, focus_meta, out, truncated, excerpt)
    payload.update(artifact_id=record["artifact_id"], artifact_path=record["artifact_path"],
                   full_content_chars=len(page.content), coverage=record.get("coverage", {}), network_access=False)
    # A cached view cannot strengthen the original source's coverage assertion.
    payload["content_complete"] = False
    if not truncated and not focus_meta.get("focused"):
        payload["incomplete_reason"] = "source_completeness_unverified"
    if record.get("error"):
        payload.update(error=record["error"], detail=record.get("detail", ""))
        if isinstance(payload["detail"], str) and len(payload["detail"]) > max(100, min(max_chars, MAX_WEB_FETCH_MAX_CHARS)):
            payload["detail"], _ = _truncate_text(payload["detail"], max(100, min(max_chars, MAX_WEB_FETCH_MAX_CHARS)))
            payload.update(diagnostic_truncated=["detail"], diagnostic_artifact_available=True)
    return _json_payload(payload)


async def fetch_web_batch(urls: list[str], **options: Any) -> str:
    """Serial fetches amortize imports and reuse one HTTP client; all errors are retained."""
    results = []
    async with httpx.AsyncClient(follow_redirects=True, timeout=options.get("timeout", DEFAULT_FETCH_TIMEOUT),
        headers={"User-Agent": DEFAULT_USER_AGENT, "Accept": DEFAULT_FETCH_ACCEPT}) as client:
        for url in urls:
            results.append(json.loads(await fetch_web_page(url, _client=client, **options)))
    failed = sum("error" in result for result in results)
    payload: dict[str, Any] = {"results": results, "failed_count": failed, "result_count": len(results)}
    if failed:
        payload["error"] = "web batch contains failed fetches"
    return _json_payload(payload)


async def research_web(
    query: str,
    max_results: int = DEFAULT_WEB_SEARCH_RESULTS,
    result_index: int = 1,
    search_type: str = "text",
    timelimit: str | None = None,
    max_chars: int = DEFAULT_WEB_FETCH_MAX_CHARS,
    focus_query: str | None = None,
    backend: str = "auto",
    selector: str | None = None,
    wait_script: str | None = None,
    timeout: float = DEFAULT_FETCH_TIMEOUT,
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
        **({"selector": selector} if selector else {}),
        **({"wait_script": wait_script} if wait_script else {}),
        **({"timeout": timeout} if timeout != DEFAULT_FETCH_TIMEOUT else {}),
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
    "fetch_web_batch",
    "fetch_web_page",
    "refocus_web_artifact",
    "research_web",
    "search_web",
]
