from __future__ import annotations

import re

_MDV2_ESCAPE_RE = re.compile(r"([_*\[\]()~`>#\+\-=|{}.!\\])")
_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*){1,}\|?\s*$")


def utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def _prefix_within_utf16_limit(text: str, limit: int) -> str:
    if limit <= 0:
        return ""
    used = 0
    parts: list[str] = []
    for ch in text:
        ch_units = utf16_len(ch)
        if used + ch_units > limit:
            break
        parts.append(ch)
        used += ch_units
    return "".join(parts)


def _escape_mdv2(text: str) -> str:
    return _MDV2_ESCAPE_RE.sub(r"\\\1", text)


def _strip_mdv2(text: str) -> str:
    cleaned = re.sub(r"\\([_*\[\]()~`>#\+\-=|{}.!\\])", r"\1", text)
    cleaned = re.sub(r"\*([^*]+)\*", r"\1", cleaned)
    cleaned = re.sub(r"(?<!\w)_([^_]+)_(?!\w)", r"\1", cleaned)
    cleaned = re.sub(r"~([^~]+)~", r"\1", cleaned)
    cleaned = re.sub(r"\|\|([^|]+)\|\|", r"\1", cleaned)
    return cleaned


def _is_table_row(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and "|" in stripped


def _wrap_markdown_tables(text: str) -> str:
    if "|" not in text or "-" not in text:
        return text

    lines = text.split("\n")
    out: list[str] = []
    in_fence = False
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip()

        if stripped.startswith("```"):
            in_fence = not in_fence
            out.append(line)
            i += 1
            continue
        if in_fence:
            out.append(line)
            i += 1
            continue

        if "|" in line and i + 1 < len(lines) and _TABLE_SEPARATOR_RE.match(lines[i + 1]):
            table_block = [line, lines[i + 1]]
            j = i + 2
            while j < len(lines) and _is_table_row(lines[j]):
                table_block.append(lines[j])
                j += 1
            out.append("```")
            out.extend(table_block)
            out.append("```")
            i = j
            continue

        out.append(line)
        i += 1

    return "\n".join(out)


def format_markdown_v2(content: str | None) -> str | None:
    if not content:
        return content

    placeholders: dict[str, str] = {}
    counter = [0]

    def _ph(value: str) -> str:
        key = f"\x00PH{counter[0]}\x00"
        counter[0] += 1
        placeholders[key] = value
        return key

    text = _wrap_markdown_tables(content)

    def _protect_fenced(match: re.Match[str]) -> str:
        raw = match.group(0)
        open_end = raw.index("\n") + 1 if "\n" in raw[3:] else 3
        opening = raw[:open_end]
        body_and_close = raw[open_end:]
        body = body_and_close[:-3]
        body = body.replace("\\", "\\\\").replace("`", "\\`")
        return _ph(opening + body + "```")

    text = re.sub(r"(```(?:[^\n]*\n)?[\s\S]*?```)", _protect_fenced, text)
    text = re.sub(r"(`[^`]+`)", lambda m: _ph(m.group(0).replace("\\", "\\\\")), text)

    def _convert_link(match: re.Match[str]) -> str:
        display = _escape_mdv2(match.group(1))
        url = match.group(2).replace("\\", "\\\\").replace(")", "\\)")
        return _ph(f"[{display}]({url})")

    text = re.sub(r"\[([^\]]+)\]\(([^()]*(?:\([^()]*\)[^()]*)*)\)", _convert_link, text)

    def _convert_header(match: re.Match[str]) -> str:
        inner = re.sub(r"\*\*(.+?)\*\*", r"\1", match.group(1).strip())
        return _ph(f"*{_escape_mdv2(inner)}*")

    text = re.sub(r"^#{1,6}\s+(.+)$", _convert_header, text, flags=re.MULTILINE)
    text = re.sub(r"\*\*(.+?)\*\*", lambda m: _ph(f"*{_escape_mdv2(m.group(1))}*"), text)
    text = re.sub(r"\*([^*\n]+)\*", lambda m: _ph(f"_{_escape_mdv2(m.group(1))}_"), text)
    text = re.sub(r"~~(.+?)~~", lambda m: _ph(f"~{_escape_mdv2(m.group(1))}~"), text)
    text = re.sub(r"\|\|(.+?)\|\|", lambda m: _ph(f"||{_escape_mdv2(m.group(1))}||"), text)

    def _convert_blockquote(match: re.Match[str]) -> str:
        prefix = match.group(1)
        body = match.group(2)
        if prefix.startswith("**") and body.endswith("||"):
            return _ph(f"{prefix} {_escape_mdv2(body[:-2])}||")
        return _ph(f"{prefix} {_escape_mdv2(body)}")

    text = re.sub(r"^((?:\*\*)?>{1,3}) (.+)$", _convert_blockquote, text, flags=re.MULTILINE)
    text = _escape_mdv2(text)

    for key in reversed(list(placeholders.keys())):
        text = text.replace(key, placeholders[key])

    code_split = re.split(r"(```[\s\S]*?```|`[^`]+`)", text)
    safe_parts: list[str] = []
    for idx, segment in enumerate(code_split):
        if idx % 2 == 1:
            safe_parts.append(segment)
            continue

        def _esc_bare(match: re.Match[str], seg: str = segment) -> str:
            start = match.start()
            ch = match.group(0)
            if start > 0 and seg[start - 1] == "\\":
                return ch
            if ch == "(" and start > 0 and seg[start - 1] == "]":
                return ch
            if ch == ")":
                before = seg[:start]
                if "](http" in before or "](" in before:
                    depth = 0
                    for j in range(start - 1, max(start - 2000, -1), -1):
                        if seg[j] == "(":
                            depth -= 1
                            if depth < 0:
                                if j > 0 and seg[j - 1] == "]":
                                    return ch
                                break
                        elif seg[j] == ")":
                            depth += 1
            return "\\" + ch

        safe_parts.append(re.sub(r"[(){}]", _esc_bare, segment))

    return "".join(safe_parts)


def _suffix(index: int, total: int, *, markdown: bool) -> str:
    raw = f" ({index}/{total})"
    if not markdown:
        return raw
    return re.sub(r" \((\d+)/(\d+)\)$", r" \\(\1/\2\\)", raw)


def _split_text(text: str, *, budget: int) -> list[str]:
    if budget <= 0:
        raise ValueError("budget must be positive")
    chunks: list[str] = []
    remaining = text
    while remaining:
        if utf16_len(remaining) <= budget:
            chunks.append(remaining)
            break
        candidate = _prefix_within_utf16_limit(remaining, budget)
        newline_idx = candidate.rfind("\n")
        if newline_idx > 0:
            candidate = remaining[:newline_idx]
            remaining = remaining[newline_idx + 1 :]
        else:
            remaining = remaining[len(candidate) :]
        chunks.append(candidate)
    return [chunk for chunk in chunks if chunk]


def chunk_for_telegram(text: str, *, limit: int = 4096, markdown: bool = True) -> list[str]:
    if text == "":
        return [""]
    if utf16_len(text) <= limit:
        return [text]

    total = 2
    while True:
        suffix_budget = max(utf16_len(_suffix(i, total, markdown=markdown)) for i in range(1, total + 1))
        payload_budget = limit - suffix_budget
        base_chunks = _split_text(text, budget=payload_budget)
        new_total = len(base_chunks)
        if new_total == total:
            return [chunk + _suffix(i + 1, total, markdown=markdown) for i, chunk in enumerate(base_chunks)]
        total = new_total
