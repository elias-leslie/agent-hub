"""Release metadata and ST error compatibility for the supported executable."""

import json

from app.cli import web_research


def test_release_description_is_static(monkeypatch, capsys):
    async def forbidden(**kwargs):
        raise AssertionError("metadata must not invoke research")

    monkeypatch.setattr(web_research, "search_web", forbidden)
    assert web_research.main(["--describe-st"]) == 0
    metadata = json.loads(capsys.readouterr().out)
    assert metadata["namespace"] == "web"
    assert metadata["st_contract_versions"] == [1]
    assert "--backend" in metadata["help"]["fetch"]
    assert metadata["usage"][0]["surface"] == "st.web"


def test_missing_query_is_a_usage_error_without_traceback(capsys):
    assert web_research.main(["search"]) == 2
    captured = capsys.readouterr()
    assert captured.err == "ERROR --query is required\n"
    assert captured.out == ""


def test_release_metadata_exposes_dom_and_cache_contracts(capsys):
    assert web_research.main(["--describe-st"]) == 0
    metadata = json.loads(capsys.readouterr().out)
    assert metadata["version"] == "1.1.0"
    for command in ("fetch", "research", "batch"):
        assert "--selector" in metadata["help"][command]
        assert "--wait-script" in metadata["help"][command]
        assert "lightpanda" in metadata["help"][command]
    assert "--artifact" in metadata["help"]["refocus"]
    assert "digest" in metadata["help"]["doctor"]
