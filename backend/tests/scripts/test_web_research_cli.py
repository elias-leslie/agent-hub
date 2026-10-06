"""Tests for the shared web research CLI entry point."""

from __future__ import annotations

import json

import pytest


def test_search_command_outputs_json(monkeypatch, capsys) -> None:
    from app.cli.web_research import main

    async def _fake_search_web(**kwargs: object) -> str:
        assert kwargs == {
            "query": "Cloudflare Markdown for Agents",
            "max_results": 5,
            "search_type": "text",
            "timelimit": None,
        }
        return json.dumps({"query": "Cloudflare Markdown for Agents", "results": []})

    monkeypatch.setattr("app.cli.web_research.search_web", _fake_search_web)

    exit_code = main(["search", "--query", "Cloudflare Markdown for Agents"])

    assert exit_code == 0
    assert '"query": "Cloudflare Markdown for Agents"' in capsys.readouterr().out


def test_search_command_accepts_positional_query_and_limit_alias(monkeypatch, capsys) -> None:
    from app.cli.web_research import main

    async def _fake_search_web(**kwargs: object) -> str:
        assert kwargs == {
            "query": "Cloudflare Markdown for Agents",
            "max_results": 3,
            "search_type": "text",
            "timelimit": None,
        }
        return json.dumps({"query": kwargs["query"], "results": []})

    monkeypatch.setattr("app.cli.web_research.search_web", _fake_search_web)

    exit_code = main(["search", "Cloudflare Markdown for Agents", "--limit", "3"])

    assert exit_code == 0
    assert '"query": "Cloudflare Markdown for Agents"' in capsys.readouterr().out


def test_fetch_command_forwards_focus_query(monkeypatch, capsys) -> None:
    from app.cli.web_research import main

    async def _fake_fetch_web_page(**kwargs: object) -> str:
        assert kwargs == {
            "url": "https://developers.cloudflare.com/fundamentals/reference/markdown-for-agents/",
            "max_chars": 12000,
            "focus_query": "how clients request markdown",
            "backend": "auto",
        }
        return json.dumps({"url": kwargs["url"], "focused": True})

    monkeypatch.setattr("app.cli.web_research.fetch_web_page", _fake_fetch_web_page)

    exit_code = main([
        "fetch",
        "--url",
        "https://developers.cloudflare.com/fundamentals/reference/markdown-for-agents/",
        "--focus-query",
        "how clients request markdown",
    ])

    assert exit_code == 0
    assert '"focused": true' in capsys.readouterr().out


def test_fetch_command_accepts_positional_url(monkeypatch, capsys) -> None:
    from app.cli.web_research import main

    async def _fake_fetch_web_page(**kwargs: object) -> str:
        assert kwargs == {
            "url": "https://developers.cloudflare.com/fundamentals/reference/markdown-for-agents/",
            "max_chars": 12000,
            "focus_query": "how clients request markdown",
            "backend": "auto",
        }
        return json.dumps({"url": kwargs["url"], "focused": True})

    monkeypatch.setattr("app.cli.web_research.fetch_web_page", _fake_fetch_web_page)

    exit_code = main([
        "fetch",
        "https://developers.cloudflare.com/fundamentals/reference/markdown-for-agents/",
        "--focus-query",
        "how clients request markdown",
    ])

    assert exit_code == 0
    assert '"focused": true' in capsys.readouterr().out


def test_research_command_forwards_combined_arguments(monkeypatch, capsys) -> None:
    from app.cli.web_research import main

    async def _fake_research_web(**kwargs: object) -> str:
        assert kwargs == {
            "query": "Cloudflare Markdown for Agents",
            "max_results": 4,
            "result_index": 2,
            "search_type": "text",
            "timelimit": None,
            "max_chars": 6000,
            "focus_query": "markdown clients",
            "backend": "auto",
        }
        return json.dumps({"query": kwargs["query"], "selected_result": {"rank": 2}})

    monkeypatch.setattr("app.cli.web_research.research_web", _fake_research_web)

    exit_code = main([
        "research",
        "--query",
        "Cloudflare Markdown for Agents",
        "--max-results",
        "4",
        "--result-index",
        "2",
        "--max-chars",
        "6000",
        "--focus-query",
        "markdown clients",
    ])

    assert exit_code == 0
    assert '"rank": 2' in capsys.readouterr().out


def test_research_command_accepts_positional_query(monkeypatch, capsys) -> None:
    from app.cli.web_research import main

    async def _fake_research_web(**kwargs: object) -> str:
        assert kwargs == {
            "query": "Cloudflare Markdown for Agents",
            "max_results": 5,
            "result_index": 1,
            "search_type": "text",
            "timelimit": None,
            "max_chars": 12000,
            "focus_query": None,
            "backend": "auto",
        }
        return json.dumps({"query": kwargs["query"], "selected_result": {"rank": 1}})

    monkeypatch.setattr("app.cli.web_research.research_web", _fake_research_web)

    exit_code = main(["research", "Cloudflare Markdown for Agents"])

    assert exit_code == 0
    assert '"rank": 1' in capsys.readouterr().out


def test_fetch_command_forwards_backend_and_outputs_compact_json(monkeypatch, capsys) -> None:
    from app.cli.web_research import main

    async def _fake_fetch_web_page(**kwargs: object) -> str:
        assert kwargs == {
            "url": "https://example.com/product",
            "max_chars": 500,
            "focus_query": None,
            "backend": "jina",
        }
        return json.dumps({"url": kwargs["url"], "fetch_backend": "jina"})

    monkeypatch.setattr("app.cli.web_research.fetch_web_page", _fake_fetch_web_page)

    exit_code = main([
        "fetch",
        "https://example.com/product",
        "--max-chars",
        "500",
        "--backend",
        "jina",
        "--compact",
    ])

    assert exit_code == 0
    assert capsys.readouterr().out == (
        '{"fetch_backend": "jina", "url": "https://example.com/product"}\n'
    )


def test_research_command_forwards_backend(monkeypatch, capsys) -> None:
    from app.cli.web_research import main

    async def _fake_research_web(**kwargs: object) -> str:
        assert kwargs["backend"] == "direct"
        return json.dumps({"query": kwargs["query"], "selected_result": {"rank": 1}})

    monkeypatch.setattr("app.cli.web_research.research_web", _fake_research_web)

    exit_code = main([
        "research",
        "SummitFlow",
        "--backend",
        "direct",
    ])

    assert exit_code == 0
    assert '"query": "SummitFlow"' in capsys.readouterr().out


def test_raw_alias_outputs_compact_json(monkeypatch, capsys) -> None:
    from app.cli.web_research import main

    async def _fake_search_web(**kwargs: object) -> str:
        return json.dumps({"query": kwargs["query"], "results": []})

    monkeypatch.setattr("app.cli.web_research.search_web", _fake_search_web)

    exit_code = main(["search", "SummitFlow", "--raw"])

    assert exit_code == 0
    assert capsys.readouterr().out == '{"query": "SummitFlow", "results": []}\n'


def test_default_output_remains_pretty_json(monkeypatch, capsys) -> None:
    from app.cli.web_research import main

    async def _fake_search_web(**kwargs: object) -> str:
        return json.dumps({"query": kwargs["query"], "results": []})

    monkeypatch.setattr("app.cli.web_research.search_web", _fake_search_web)

    exit_code = main(["search", "SummitFlow"])

    assert exit_code == 0
    assert capsys.readouterr().out == '{\n  "query": "SummitFlow",\n  "results": []\n}\n'


def test_fetch_command_rejects_unknown_backend() -> None:
    from app.cli.web_research import main

    with pytest.raises(SystemExit) as exc_info:
        main(["fetch", "https://example.com", "--backend", "unknown"])

    assert exc_info.value.code == 2


def test_error_payload_keeps_failure_exit_in_compact_mode(monkeypatch, capsys) -> None:
    from app.cli.web_research import main

    async def _fake_fetch_web_page(**kwargs: object) -> str:
        return json.dumps({"error": "request failed", "url": kwargs["url"]})

    monkeypatch.setattr("app.cli.web_research.fetch_web_page", _fake_fetch_web_page)

    exit_code = main(["fetch", "https://example.com", "--compact"])

    assert exit_code == 1
    assert capsys.readouterr().out == (
        '{"error": "request failed", "url": "https://example.com"}\n'
    )


def test_benchmark_command_bounds_inputs_and_fails_unsuccessful_result(monkeypatch, capsys) -> None:
    from app.cli.web_research import main

    async def _fake_benchmark_web(iterations: int, max_chars: int) -> str:
        assert iterations == 10
        assert max_chars == 5000
        return json.dumps({"benchmark": "st web deterministic fetch", "passed": False})

    monkeypatch.setattr("app.cli.web_research.benchmark_web", _fake_benchmark_web)

    exit_code = main([
        "benchmark",
        "--iterations",
        "99",
        "--max-chars",
        "100000",
        "--compact",
    ])

    assert exit_code == 1
    assert capsys.readouterr().out == (
        '{"benchmark": "st web deterministic fetch", "passed": false}\n'
    )


def test_fetch_forwards_lightpanda_options(monkeypatch, capsys):
    from app.cli.web_research import main
    async def fake_fetch(**kwargs):
        assert kwargs == {"url": "https://example.com", "max_chars": 12000, "focus_query": None,
                          "backend": "lightpanda", "selector": "article", "wait_script": "document.ready", "timeout": 3.5}
        return json.dumps({"content": "Evidence", "content_complete": False})
    monkeypatch.setattr("app.cli.web_research.fetch_web_page", fake_fetch)
    assert main(["fetch", "https://example.com", "--backend", "lightpanda", "--selector", "article", "--wait-script", "document.ready", "--timeout", "3.5"]) == 0
    assert json.loads(capsys.readouterr().out)["content_complete"] is False


def test_fetch_help_explains_scoped_readiness_and_coverage(capsys):
    from app.cli.web_research import main
    with pytest.raises(SystemExit) as exc:
        main(["fetch", "--help"])
    assert exc.value.code == 0
    help_text = capsys.readouterr().out
    assert '--selector article' in help_text
    assert 'document.querySelector("article")?.innerText.includes("Conclusion")' in help_text
    assert "inline scripts and styles" in help_text
    assert "verify the returned facts after readiness passes" in help_text
    assert "direct content_complete describes the returned extraction view" in help_text
    assert "coverage.source_completeness remains unverified" in help_text
    normalized_help = " ".join(help_text.split())
    assert "Local --raw/--compact emits complete result JSON through ST" in normalized_help
    assert "global st --no-compact keeps the web details receipt" in normalized_help


def test_batch_failure_returns_nonzero_with_all_results(monkeypatch, capsys):
    from app.cli.web_research import main
    async def fake_batch(urls, **kwargs):
        assert urls == ["https://example.com/good", "https://example.com/fail"]
        assert kwargs["max_chars"] == 12000 and kwargs["backend"] == "direct"
        return json.dumps({"results": [{"content": "Good", "artifact_id": "saved"}, {"error": "Failed"}],
                           "failed_count": 1, "error": "web batch contains failed fetches"})
    monkeypatch.setattr("app.cli.web_research.fetch_web_batch", fake_batch)
    assert main(["batch", "https://example.com/good", "https://example.com/fail", "--backend", "direct"]) == 1
    assert len(json.loads(capsys.readouterr().out)["results"]) == 2


def test_refocus_uses_owner_cache_contract(monkeypatch, capsys):
    from app.cli.web_research import main
    def fake_refocus(artifact, **kwargs):
        assert artifact == "a" * 32
        assert kwargs == {"max_chars": 12000, "focus_query": "qualifications"}
        return json.dumps({"content": "Evidence", "network_access": False})
    monkeypatch.setattr("app.cli.web_research.refocus_web_artifact", fake_refocus)
    assert main(["refocus", "a" * 32, "--focus-query", "qualifications"]) == 0
    assert json.loads(capsys.readouterr().out)["network_access"] is False


def test_doctor_unusable_returns_nonzero(monkeypatch, capsys):
    from app.cli.web_research import main
    async def fake_doctor(timeout):
        assert timeout == 20.0
        return {"usable": False, "error": "Lightpanda verification failed", "detail": "pin mismatch"}
    monkeypatch.setattr("app.cli.web_research.doctor_lightpanda", fake_doctor)
    assert main(["doctor"]) == 1
    assert json.loads(capsys.readouterr().out)["usable"] is False
