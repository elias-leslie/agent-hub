"""Full extraction reuse, error fidelity, and pinned bounded DOM retrieval."""
from __future__ import annotations

import hashlib
import json
import os
import sys
from unittest.mock import AsyncMock

import httpx
import pytest

from app.services.tools import _executor_web as web
from app.services.tools import _executor_web_html as html
from app.services.tools import _executor_web_lightpanda as lp
from app.services.tools._executor_web_artifacts import load_artifact


@pytest.fixture(autouse=True)
def owner_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_HUB_WEB_CACHE_DIR", str(tmp_path / "cache"))
    lp._VERIFIED.clear()


@pytest.fixture
def pinned_binary(monkeypatch, tmp_path):
    path = tmp_path / "lightpanda"
    path.write_text(f'''#!{sys.executable}
import json, os, sys, time
from pathlib import Path
if sys.argv[1] == "version":
    print("fixture-version")
    raise SystemExit(0)
url = sys.argv[2]
if url.endswith("bulky"):
    print("{{" + "!" * 30000)
    print("diagnostic " * 4000, file=sys.stderr)
    raise SystemExit(1)
if url.endswith("timeout"):
    Path({str(tmp_path / "pid")!r}).write_text(str(os.getpid()))
    print("partial evidence", flush=True)
    time.sleep(5)
receipt = {{"url": url, "http_status": 200, "content": "Ready document body", "error": None}}
if url.endswith("missing"):
    receipt.pop("content")
if url.endswith("http-error"):
    receipt["http_status"] = 503
if url.endswith("wait-failure"):
    receipt["error"] = "Timeout"
    receipt["content"] = "Preparing document"
if url.endswith("scoped"):
    assert "--dump-selector" in sys.argv and sys.argv[sys.argv.index("--dump-selector")+1] == "article"
    assert "--wait-script" in sys.argv and sys.argv[sys.argv.index("--wait-script")+1] == "document.ready"
    assert "--terminate-ms" in sys.argv
    assert "--wait-ms" not in sys.argv
    assert os.environ["LIGHTPANDA_DISABLE_TELEMETRY"] == "1"
print(json.dumps(receipt))
''')
    path.chmod(0o700)
    monkeypatch.setenv("AGENT_HUB_WEB_LIGHTPANDA_BINARY", str(path))
    monkeypatch.setenv("AGENT_HUB_WEB_LIGHTPANDA_VERSION", "fixture-version")
    monkeypatch.setenv("AGENT_HUB_WEB_LIGHTPANDA_SHA256", hashlib.sha256(path.read_bytes()).hexdigest())
    return path


def test_html_comments_preserve_structured_relationships():
    content = html._structured_article_markdown("<article><!--comment--><h1>Access</h1><p>Trial accounts qualify.</p><!-- tail --><ul><li>Owner consent</li></ul></article>")
    assert "# Access" in content
    assert "Trial accounts qualify." in content
    assert "- Owner consent" in content
    assert "comment" not in content


def test_optional_renderer_failure_preserves_trafilatura(monkeypatch):
    monkeypatch.setattr(html, "_structured_article_markdown", lambda value: (_ for _ in ()).throw(ValueError("optional renderer failed")))
    source = "<article><h1>Useful evidence</h1>" + "<p>This article describes eligibility and owner consent for trial accounts in substantial detail.</p>" * 15 + "</article>"
    _, markdown = html._extract_markdown_payload(source, "https://example.com/article")
    assert "eligibility and owner consent" in markdown


@pytest.mark.asyncio
async def test_extraction_valueerror_is_not_unsupported_mime(monkeypatch):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, text="<article>Evidence</article>", headers={"content-type": "text/html"}))) as client:
        monkeypatch.setattr(web, "_extract_page_content", lambda *args: (_ for _ in ()).throw(ValueError("extractor failed")))
        result = json.loads(await web.fetch_web_page("https://example.com", backend="direct", _client=client))
    assert result["error"] == "fetch_web_page extraction failed"
    assert result["detail"] == "extractor failed"
    record = load_artifact(result["artifact_id"])
    assert record["artifact_kind"] == "raw_response"
    assert "<article>Evidence" in record["content"]


@pytest.mark.asyncio
async def test_unsupported_mime_is_distinct():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"image-data", headers={"content-type": "image/png"}))) as client:
        result = json.loads(await web.fetch_web_page("https://example.com", backend="direct", _client=client))
    assert result["error"] == "fetch_web_page only supports text-like responses"
    assert result["content_type"] == "image/png"


@pytest.mark.asyncio
async def test_full_artifact_refocus_preserves_citation_and_never_fetches(monkeypatch):
    body = "# Access\n\n" + "General documentation. " * 100 + "\n\n## Qualifications\n\nTrial accounts require owner consent."
    page = html._PageExtraction(body, "markdown", title="Access guide", site_name="Example", author="Author", published="2026-10-05", published_date_inferred=True)
    monkeypatch.setattr(web, "_extract_page_content", lambda *args: page)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=body, headers={"content-type": "text/html"}))) as client:
        first = json.loads(await web.fetch_web_page("https://example.com", max_chars=100, backend="direct", _client=client))
    assert first["truncated"] and len(first["content"]) <= 100
    assert len(load_artifact(first["artifact_id"])["content"]) == len(body)
    monkeypatch.setattr(web.httpx, "AsyncClient", lambda *args, **kwargs: pytest.fail("refocus must not use network"))
    result = json.loads(web.refocus_web_artifact(first["artifact_path"], max_chars=400, focus_query="Trial accounts owner consent"))
    assert "Trial accounts require owner consent" in result["content"]
    assert result["title"] == "Access guide" and result["author"] == "Author"
    assert result["published_date_inferred"] is True
    assert result["network_access"] is False and result["content_complete"] is False
    assert result["coverage"] == load_artifact(first["artifact_id"])["coverage"]


@pytest.mark.parametrize("reference", ["../arbitrary.json", "/tmp/arbitrary.json", "https://example.com/artifact"])
def test_refocus_rejects_untrusted_paths(reference):
    result = json.loads(web.refocus_web_artifact(reference))
    assert result["error"] == "web artifact refocus failed"


def test_refocus_rejects_symlink(monkeypatch, tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / ("a" * 32 + ".json")).symlink_to(tmp_path / "external.json")
    assert "error" in json.loads(web.refocus_web_artifact(str(cache / ("a" * 32 + ".json"))))


@pytest.mark.asyncio
async def test_cache_write_failure_keeps_good_content(monkeypatch):
    monkeypatch.setattr(web, "save_artifact", lambda *args: (_ for _ in ()).throw(OSError("cache is read-only")))
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, text="Useful readable text", headers={"content-type": "text/plain"}))) as client:
        result = json.loads(await web.fetch_web_page("https://example.com", backend="direct", _client=client))
    assert result["content"] == "Useful readable text"
    assert result["coverage"]["full_extraction_retained"] is False
    assert result["artifact_error"] == "cache is read-only"
    assert result["stages"][-1]["stage"] == "artifact_write"


@pytest.mark.asyncio
async def test_lp_scoping_readiness_and_unverified_coverage(pinned_binary):
    result = json.loads(await web.fetch_web_page("https://example.com/scoped", backend="lightpanda", selector="article", wait_script="document.ready"))
    assert "error" not in result
    assert result["coverage"]["scope"] == "selector"
    assert result["coverage"]["readiness"] == "predicate_passed"
    assert result["content_complete"] is False
    assert result["incomplete_reason"] == "source_completeness_unverified"
    assert load_artifact(result["artifact_id"])["content"] == "Ready document body"
    assert result["lightpanda"]["pinned_version"] == "fixture-version"


@pytest.mark.asyncio
@pytest.mark.parametrize("suffix, expected", [("missing", "invalid fetch receipt"), ("http-error", "HTTP request failed"), ("wait-failure", "Timeout")])
async def test_lp_failure_is_explicit_and_retained(pinned_binary, suffix, expected):
    result = json.loads(await web.fetch_web_page(f"https://example.com/{suffix}", backend="lightpanda", wait_script="false"))
    assert expected in (result["error"] + result.get("detail", ""))
    assert result["coverage"]["readiness"] == "failed"
    assert load_artifact(result["artifact_id"])["backend_failure"]
    if suffix == "wait-failure":
        assert result["content"] == "Preparing document"
        assert load_artifact(result["artifact_id"])["content"] == "Preparing document"


@pytest.mark.asyncio
async def test_lp_timeout_kills_reaps_and_preserves_partial_evidence(pinned_binary):
    result = json.loads(await web.fetch_web_page("https://example.com/timeout", backend="lightpanda", timeout=0.15))
    assert result["error"] == "Lightpanda fetch timed out"
    pid = int((pinned_binary.parent / "pid").read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    assert "partial evidence" in load_artifact(result["artifact_id"])["backend_failure"]["raw_receipt"]


@pytest.mark.asyncio
async def test_lp_large_failure_diagnostics_are_previews_of_verbatim_artifact(pinned_binary):
    result = json.loads(await web.fetch_web_page("https://example.com/bulky", backend="lightpanda", max_chars=200))
    assert result["error"] == "Lightpanda fetch failed"
    assert len(result["backend_failure"]["raw_receipt"]) <= 200
    assert len(result["backend_failure"]["stderr"]) <= 200
    assert "backend_failure.raw_receipt" in result["diagnostic_truncated"]
    assert result["diagnostic_artifact_available"] is True
    record = load_artifact(result["artifact_id"])
    assert record["backend_failure"]["raw_receipt"] == "{" + "!" * 30000 + "\n"
    assert record["backend_failure"]["stderr"] == "diagnostic " * 4000 + "\n"


@pytest.mark.asyncio
async def test_lp_pin_mismatch_does_not_execute(monkeypatch, pinned_binary):
    monkeypatch.setenv("AGENT_HUB_WEB_LIGHTPANDA_SHA256", "0" * 64)
    monkeypatch.setattr(lp, "_run", AsyncMock(side_effect=AssertionError("must not execute an unverified binary")))
    result = await lp.doctor_lightpanda()
    assert result["usable"] is False and "SHA256" in result["detail"]


@pytest.mark.asyncio
async def test_lp_override_requires_all_pins(monkeypatch, pinned_binary):
    monkeypatch.delenv("AGENT_HUB_WEB_LIGHTPANDA_VERSION")
    result = await lp.doctor_lightpanda()
    assert result["usable"] is False and "paired" in result["detail"]


@pytest.mark.asyncio
async def test_lp_version_mismatch(pinned_binary, monkeypatch):
    monkeypatch.setenv("AGENT_HUB_WEB_LIGHTPANDA_VERSION", "wrong-version")
    result = await lp.doctor_lightpanda()
    assert result["usable"] is False and "version pin mismatch" in result["detail"]


@pytest.mark.asyncio
async def test_lp_batch_verification_cache_invalidates_on_binary_change(pinned_binary, monkeypatch):
    verify = lp._verify_binary
    calls = []
    def track(path, digest):
        calls.append(path)
        verify(path, digest)
    monkeypatch.setattr(lp, "_verify_binary", track)
    assert (await lp.doctor_lightpanda(force=False))["usable"]
    assert (await lp.doctor_lightpanda(force=False))["verification_cached"]
    assert len(calls) == 1
    pinned_binary.write_text(pinned_binary.read_text() + "\n# changed\n")
    assert not (await lp.doctor_lightpanda(force=False))["usable"]
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_batch_serial_reuses_one_client_and_reports_mixed_failure(monkeypatch):
    real_client = httpx.AsyncClient
    calls = []
    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(503 if request.url.path == "/fail" else 200, text="Extracted body", headers={"content-type": "text/plain"})
    created = []
    def factory(**kwargs):
        client = real_client(transport=httpx.MockTransport(handler), **kwargs)
        created.append(client)
        return client
    monkeypatch.setattr(web.httpx, "AsyncClient", factory)
    result = json.loads(await web.fetch_web_batch(["https://example.com/good", "https://example.com/fail", "https://example.com/last"], backend="direct"))
    assert result["failed_count"] == 1 and result["result_count"] == 3 and "error" in result
    assert calls == ["https://example.com/good", "https://example.com/fail", "https://example.com/last"]
    assert len(created) == 1 and created[0].is_closed
    assert result["results"][0]["artifact_id"] and result["results"][2]["artifact_id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("name, primary", [("fetch_web_page", {"url": "https://example.com"}), ("research_web", {"query": "eligibility"})])
async def test_web_tool_dispatch_forwards_dom_contract(monkeypatch, tmp_path, name, primary):
    from app.services.tools.direct_executor import DirectToolExecutor
    from app.services.tools.tool_definitions import get_agent_tools
    # Web tools are intentionally provisioned to research profiles; standard
    # coding profiles expose the shell/file surface instead.
    research_tools = get_agent_tools("vantage-research")
    assert research_tools is not None
    tools = {tool["name"]: tool for tool in research_tools}
    input_schema = tools[name]["input_schema"]
    assert isinstance(input_schema, dict)
    schema = input_schema["properties"]
    assert isinstance(schema, dict)
    backend_schema = schema["backend"]
    assert isinstance(backend_schema, dict)
    backend_choices = backend_schema["enum"]
    assert isinstance(backend_choices, list)
    assert "lightpanda" in backend_choices
    assert {"selector", "wait_script", "timeout"}.issubset(schema)
    mock = AsyncMock(return_value='{"content":"Scoped evidence"}')
    attr = "_fetch_web_page" if name == "fetch_web_page" else "_research_web"
    monkeypatch.setattr(f"app.services.tools.direct_executor_core.{attr}", mock)
    result = await DirectToolExecutor(str(tmp_path)).dispatch(name, {**primary, "backend": "lightpanda", "selector": "article", "wait_script": "document.ready", "timeout": 4})
    assert json.loads(result)["content"] == "Scoped evidence"
    assert mock.call_args.kwargs["selector"] == "article"
    assert mock.call_args.kwargs["wait_script"] == "document.ready"
    assert mock.call_args.kwargs["timeout"] == 4


@pytest.mark.asyncio
async def test_auto_fallback_artifact_retains_original_extraction_failure(monkeypatch):
    def extract(*args):
        raise RuntimeError("supported HTML extractor failure")
    monkeypatch.setattr(web, "_extract_page_content", extract)
    def handler(request):
        if request.url.host == "r.jina.ai":
            return httpx.Response(200, text="# Recovered article", headers={"content-type": "text/markdown"})
        return httpx.Response(200, text="<article>Raw evidence</article>", headers={"content-type": "text/html"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = json.loads(await web.fetch_web_page("https://example.com", backend="auto", _client=client))
    assert result["fetch_backend"] == "jina"
    assert result["direct_failure"]["error"] == "fetch_web_page extraction failed"
    record = load_artifact(result["artifact_id"])
    assert record["direct_failure"]["artifact_id"] == result["direct_failure"]["artifact_id"]
    assert [stage["stage"] for stage in record["stages"]] == ["direct_request", "direct_extraction", "jina_request"]
