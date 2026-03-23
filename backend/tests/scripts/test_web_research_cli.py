"""Tests for the shared web research CLI entry point."""

from __future__ import annotations

import json


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


def test_fetch_command_forwards_focus_query(monkeypatch, capsys) -> None:
    from app.cli.web_research import main

    async def _fake_fetch_web_page(**kwargs: object) -> str:
        assert kwargs == {
            "url": "https://developers.cloudflare.com/fundamentals/reference/markdown-for-agents/",
            "max_chars": 12000,
            "focus_query": "how clients request markdown",
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
