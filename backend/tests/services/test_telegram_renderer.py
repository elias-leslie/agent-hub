from __future__ import annotations

from app.services.telegram_renderer import (
    _escape_mdv2,
    _strip_mdv2,
    _wrap_markdown_tables,
    chunk_for_telegram,
    format_markdown_v2,
    utf16_len,
)


def test_escape_mdv2_escapes_special_characters() -> None:
    assert _escape_mdv2("Hello (world)!") == "Hello \\(world\\)\\!"


def test_strip_mdv2_removes_escape_and_format_markers() -> None:
    assert _strip_mdv2(r"*bold* _italic_ look\! ~gone~") == "bold italic look! gone"


def test_wrap_markdown_tables_fences_simple_pipe_table() -> None:
    text = "| Name | Value |\n| --- | --- |\n| Jenny | Ready |"

    result = _wrap_markdown_tables(text)

    assert result.startswith("```\n| Name | Value |")
    assert result.endswith("| Jenny | Ready |\n```")


def test_format_markdown_v2_preserves_code_and_converts_basic_markdown() -> None:
    text = "# Title\nThis is **bold** and *italic* with `code()` and [Link!](https://example.com/path_(1))."

    result = format_markdown_v2(text)

    assert result is not None
    assert "*Title*" in result
    assert "*bold*" in result
    assert "_italic_" in result
    assert "`code()`" in result
    assert "[Link\\!](https://example.com/path_\\(1\\))" in result


def test_utf16_len_counts_astral_symbols_as_two_code_units() -> None:
    assert utf16_len("🙂") == 2


def test_chunk_for_telegram_respects_utf16_limit_and_adds_markdown_suffixes() -> None:
    chunks = chunk_for_telegram("x" * 25, limit=12, markdown=True)

    assert len(chunks) > 1
    assert all(utf16_len(chunk) <= 12 for chunk in chunks)
    total = len(chunks)
    assert chunks[0].endswith(rf"\(1/{total}\)")
    assert chunks[-1].endswith(rf"\({total}/{total}\)")
