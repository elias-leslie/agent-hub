"""High-confidence secret floor applied before anything is stored or embedded.

Only token shapes that are near-certain credentials: a false positive costs a
few characters of history, a miss stores a live key and sends it to the
embedding API. Patterns are linear (bounded or disjoint classes, no nested
quantifiers). This module imports only the standard library because models
import it.
"""

from __future__ import annotations

import bisect
import re
from itertools import pairwise
from typing import Any

_KEY_BODY = r"[A-Za-z0-9+/=\s\\:,.\-]"

# Escape introducers, raw or written out in JSON or quoted text. The written-out
# forms take the whole run of backslashes before them: each level of JSON nesting
# adds more (three two levels in, 15 four levels in), and a code that leaves a
# stray backslash behind would still cut a token. A match starts only at the
# first backslash of a run, so each run is scanned once: linear.
_ESCAPED = r"(?<!\\)\\+"
_ESC = rf"(?:\x1b|{_ESCAPED}(?:u001[bB]|x1[bB]|033|e))"
# The 8-bit CSI, raw or written out.
_C1_CSI = rf"(?:\x9b|{_ESCAPED}(?:u009[bB]|x9[bB]|233))"
# A terminal control sequence (colour, erase) of any length: a combined truecolor
# SGR runs past 20 parameter bytes. The three byte classes are disjoint, so a scan
# from each introducer stops at the first byte that fits none: linear.
_CSI = rf"(?:{_ESC}\[|{_C1_CSI})[0-?]*[ -/]*[@-~]"
_TERMINAL_CODE = re.compile(_CSI)
_TOKEN_SPAN = 320  # longest prefixed token below: an 11-character prefix and 255 body characters

# Where a token may start: not right after a letter, digit or underscore, except
# after an escape that leaves one there: ``\\n``, ``\\a`` (an OSC 8 link's BEL),
# ``\\x22``, ``\\u0022``, ``\\042`` in JSON or quoted text, ``%3D`` (or ``%253D``)
# in a URL, or the ``;31m`` tail of a colour code cut off by a chunk boundary. A
# token inside a longer identifier stays. A whole terminal code before a token
# (``grep --color``, raw or JSON-escaped) is consumed as ``esc`` and put back in
# the replacement.
_START = (
    r"(?:(?<![A-Za-z0-9_])|(?<=\\[abfnrtv0])|(?<=\\[0-7]{3})|(?<=\\x[0-9A-Fa-f]{2})"
    r"|(?<=\\u[0-9A-Fa-f]{4})|(?<=\\U[0-9A-Fa-f]{8})|(?<=%[0-9A-Fa-f]{2})|(?<=%25[0-9A-Fa-f]{2})"
    rf"|(?<=[0-9;:\[]m)|(?P<esc>{_CSI}))"
)

SECRET_PATTERNS: dict[str, re.Pattern[str]] = {
    # A whole PEM block when its END line is present, else the header and the
    # base64 lines that follow it (also as escaped ``\\n`` inside JSON text).
    # A bare header (prose or code naming it) is not key material. The body
    # scan is bounded so many headers without an END stay linear.
    "private_key": re.compile(
        r"-----BEGIN [A-Z0-9 ]{0,40}PRIVATE KEY(?: BLOCK)?-----"
        rf"(?:{_KEY_BODY}{{0,8192}}?-----END [A-Z0-9 ]{{0,40}}PRIVATE KEY(?: BLOCK)?-----"
        r"|(?:(?:\s|\\[nr])+[A-Za-z0-9+/=]{40,})+)"
    ),
    "aws_access_key": re.compile(rf"{_START}AKIA[0-9A-Z]{{16}}(?![0-9A-Z])"),
    "github_token": re.compile(
        rf"{_START}(?:gh[pousr]_[A-Za-z0-9]{{36,255}}|github_pat_[A-Za-z0-9_]{{22,255}})"
    ),
    "gitlab_token": re.compile(rf"{_START}glpat-[A-Za-z0-9_\-]{{20,255}}"),
    "slack_token": re.compile(rf"{_START}xox[abposr]-[A-Za-z0-9\-]{{10,255}}"),
    "anthropic_key": re.compile(rf"{_START}sk-ant-[A-Za-z0-9_\-]{{20,255}}"),
    "stripe_live_key": re.compile(rf"{_START}[rs]k_live_[A-Za-z0-9]{{20,255}}"),
}
_PREFIXED = [pattern for kind, pattern in SECRET_PATTERNS.items() if kind != "private_key"]


def redact_secrets(text: str) -> tuple[str, dict[str, int]]:
    """Replace each secret match with ``[REDACTED:<kind>]``; return counts per kind."""
    counts: dict[str, int] = {}
    text = _redact_split_tokens(text, counts)
    for kind, pattern in SECRET_PATTERNS.items():
        tag = f"[REDACTED:{kind}]"
        text, hits = pattern.subn(lambda match, tag=tag: (match.groupdict().get("esc") or "") + tag, text)
        if hits:
            counts[kind] = counts.get(kind, 0) + hits
    return text, counts


def _redact_split_tokens(text: str, counts: dict[str, int]) -> str:
    """Redact tokens that terminal codes cut apart (``rg``/``grep --color`` highlighting
    part of a token, a coloured ``git diff`` of a key file).

    The floor runs on the text with every code removed; a match that spanned a
    code is replaced in the original, and the codes inside it are kept after the
    tag so the terminal state is unchanged. Matches no code cuts are left to the
    plain pass.
    """
    codes = list(_TERMINAL_CODE.finditer(text))
    if not codes:
        return text
    kept_at: list[int] = []  # stripped offset where each kept piece starts
    orig_at: list[int] = []  # the same piece's offset in ``text``
    pieces: list[str] = []
    cursor = stripped_len = 0
    for code in [*codes, None]:
        end = code.start() if code else len(text)
        if end > cursor:
            kept_at.append(stripped_len)
            orig_at.append(cursor)
            pieces.append(text[cursor:end])
            stripped_len += end - cursor
        if code:
            cursor = code.end()
    stripped = "".join(pieces)

    def to_orig(index: int) -> int:
        piece = bisect.bisect_right(kept_at, index) - 1
        return orig_at[piece] + index - kept_at[piece]

    # A removed code still marks where a token may start, even after a letter.
    glued = [at for at in kept_at[1:] if stripped[at - 1].isalnum() or stripped[at - 1] == "_"]
    # A code with a whole token right after it ends whatever came before: without
    # the code, the token before would run on into this one's prefix (``ghp``,
    # ``sk``) and leave its body behind. Matches stay inside these segments.
    heads = [
        at
        for at in kept_at[1:]
        if any(pattern.match(stripped[at : at + _TOKEN_SPAN]) for pattern in _PREFIXED)
    ]
    bounds = [0, *heads, len(stripped)]
    spans: list[tuple[int, int, str]] = []
    for kind, pattern in SECRET_PATTERNS.items():
        matches = [(match, 0) for lo, hi in pairwise(bounds) for match in pattern.finditer(stripped, lo, hi)]
        if kind != "private_key":
            for at in glued:
                hi = min(at + _TOKEN_SPAN, bounds[bisect.bisect_right(bounds, at)])
                if match := pattern.match(stripped[at:hi]):
                    matches.append((match, at))
        for match, offset in matches:
            token_start = offset + (match.end("esc") if match.groupdict().get("esc") else match.start())
            token_end = offset + match.end()
            start, end = to_orig(token_start), to_orig(token_end - 1) + 1
            if end - start > token_end - token_start:  # a code sits inside the token
                spans.append((start, end, kind))
    if not spans:
        return text
    code_starts = [code.start() for code in codes]
    out: list[str] = []
    cursor = 0
    for start, end, kind in sorted(spans):
        if start < cursor:  # overlaps a span already replaced
            continue
        inner = []
        index = bisect.bisect_left(code_starts, start)
        while index < len(codes) and codes[index].end() <= end:
            inner.append(codes[index].group())
            index += 1
        out.append(f"{text[cursor:start]}[REDACTED:{kind}]{''.join(inner)}")
        counts[kind] = counts.get(kind, 0) + 1
        cursor = end
    out.append(text[cursor:])
    return "".join(out)


def redact_text(text: str | None) -> str | None:
    """``redact_secrets`` for optional text columns, without the counts."""
    return text if not text else redact_secrets(text)[0]


def redact_value(value: Any) -> Any:
    """Redact every string inside a JSON-like value (dict keys are left alone).

    Returns the original object when nothing matched, so unchanged JSON
    columns are not marked dirty.
    """
    if isinstance(value, str):
        redacted, counts = redact_secrets(value)
        return redacted if counts else value
    if isinstance(value, list):
        items = [redact_value(item) for item in value]
        return value if all(new is old for new, old in zip(items, value, strict=True)) else items
    if isinstance(value, dict):
        redacted = {key: redact_value(item) for key, item in value.items()}
        return value if all(redacted[key] is item for key, item in value.items()) else redacted
    return value
