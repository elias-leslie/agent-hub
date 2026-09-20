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
