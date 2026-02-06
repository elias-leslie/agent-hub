from __future__ import annotations

from app.services.memory.privacy_filter import (
    apply_privacy_filter,
    strip_memory_tags,
    strip_private_tags,
)


class TestStripPrivateTags:
    def test_basic_private_tag(self) -> None:
        content = "before <private>secret</private> after"
        result, count = strip_private_tags(content)
        assert result == "before [REDACTED] after"
        assert count == 1

    def test_multiline_private_content(self) -> None:
        content = "start <private>\nline1\nline2\n</private> end"
        result, count = strip_private_tags(content)
        assert result == "start [REDACTED] end"
        assert count == 1

    def test_multiple_private_tags(self) -> None:
        content = "<private>a</private> middle <private>b</private>"
        result, count = strip_private_tags(content)
        assert result == "[REDACTED] middle [REDACTED]"
        assert count == 2

    def test_no_private_tags(self) -> None:
        content = "nothing to strip here"
        result, count = strip_private_tags(content)
        assert result == "nothing to strip here"
        assert count == 0

    def test_empty_content(self) -> None:
        result, count = strip_private_tags("")
        assert result == ""
        assert count == 0

    def test_nested_private_tags(self) -> None:
        content = "<private>outer <private>inner</private> still outer</private> after"
        result, _ = strip_private_tags(content)
        assert "after" in result
        assert "<private>" not in result

    def test_unclosed_private_tag(self) -> None:
        content = "before <private>unclosed content"
        result, count = strip_private_tags(content)
        assert result == "before <private>unclosed content"
        assert count == 0

    def test_empty_private_tag(self) -> None:
        content = "before <private></private> after"
        result, count = strip_private_tags(content)
        assert result == "before [REDACTED] after"
        assert count == 1


class TestStripMemoryTags:
    def test_basic_memory_tag(self) -> None:
        content = "before <memory>stored</memory> after"
        result, count = strip_memory_tags(content)
        assert result == "before  after"
        assert count == 1

    def test_multiline_memory_content(self) -> None:
        content = "start <memory>\nrecursive\nstorage\n</memory> end"
        result, count = strip_memory_tags(content)
        assert result == "start  end"
        assert count == 1

    def test_multiple_memory_tags(self) -> None:
        content = "<memory>x</memory> gap <memory>y</memory>"
        result, count = strip_memory_tags(content)
        assert result == " gap "
        assert count == 2

    def test_no_memory_tags(self) -> None:
        content = "plain text"
        result, count = strip_memory_tags(content)
        assert result == "plain text"
        assert count == 0

    def test_empty_content(self) -> None:
        result, count = strip_memory_tags("")
        assert result == ""
        assert count == 0

    def test_unclosed_memory_tag(self) -> None:
        content = "before <memory>unclosed"
        result, count = strip_memory_tags(content)
        assert result == "before <memory>unclosed"
        assert count == 0


class TestApplyPrivacyFilter:
    def test_combined_filtering(self) -> None:
        content = "<private>secret</private> visible <memory>meta</memory> text"
        result, stats = apply_privacy_filter(content)
        assert "[REDACTED]" in result
        assert "secret" not in result
        assert "meta" not in result
        assert "visible" in result
        assert "text" in result
        assert stats["private_tags_stripped"] == 1
        assert stats["memory_tags_stripped"] == 1

    def test_no_tags_passthrough(self) -> None:
        content = "clean content with no tags"
        result, stats = apply_privacy_filter(content)
        assert result == "clean content with no tags"
        assert stats["private_tags_stripped"] == 0
        assert stats["memory_tags_stripped"] == 0

    def test_empty_content(self) -> None:
        result, stats = apply_privacy_filter("")
        assert result == ""
        assert stats["private_tags_stripped"] == 0
        assert stats["memory_tags_stripped"] == 0

    def test_only_private_tags(self) -> None:
        content = "<private>all secret</private>"
        result, stats = apply_privacy_filter(content)
        assert result == "[REDACTED]"
        assert stats["private_tags_stripped"] == 1
        assert stats["memory_tags_stripped"] == 0

    def test_only_memory_tags(self) -> None:
        content = "<memory>recursive</memory>"
        result, stats = apply_privacy_filter(content)
        assert result == ""
        assert stats["private_tags_stripped"] == 0
        assert stats["memory_tags_stripped"] == 1

    def test_private_applied_before_memory(self) -> None:
        content = "<private>secret <memory>nested</memory> end</private> visible"
        result, stats = apply_privacy_filter(content)
        assert "secret" not in result
        assert "visible" in result
        assert stats["private_tags_stripped"] == 1
