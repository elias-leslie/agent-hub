"""Streaming JSON repair + partial parsing (port of pi-mono ``utils/json-parse.ts``).

Pi-mono's TS version uses ``partial-json``; we depend on the well-maintained
``json-repair`` Python package, which provides equivalent best-effort repair
of malformed/partial JSON. The :func:`repair_json` function performs the
same string-level escape repair as pi-mono so the two implementations
behave identically on well-formed but slightly-broken JSON.
"""

from __future__ import annotations

import json
from typing import Any

try:
    from json_repair import repair_json as _partial_repair
except ImportError:  # pragma: no cover — optional dependency
    _partial_repair = None


_VALID_JSON_ESCAPES = frozenset({'"', "\\", "/", "b", "f", "n", "r", "t", "u"})
_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")


def _is_control_character(char: str) -> bool:
    cp = ord(char)
    return 0x00 <= cp <= 0x1F


def _escape_control_character(char: str) -> str:
    if char == "\b":
        return "\\b"
    if char == "\f":
        return "\\f"
    if char == "\n":
        return "\\n"
    if char == "\r":
        return "\\r"
    if char == "\t":
        return "\\t"
    return f"\\u{ord(char):04x}"


def repair_json(text: str) -> str:
    """Repair malformed JSON-string literals.

    Escapes raw control characters inside strings and doubles backslashes
    that precede invalid escape characters. Pi-mono ``repairJson`` parity.
    """

    out: list[str] = []
    in_string = False
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]

        if not in_string:
            out.append(ch)
            if ch == '"':
                in_string = True
            i += 1
            continue

        if ch == '"':
            out.append(ch)
            in_string = False
            i += 1
            continue

        if ch == "\\":
            if i + 1 >= n:
                out.append("\\\\")
                i += 1
                continue
            nxt = text[i + 1]

            if nxt == "u":
                digits = text[i + 2 : i + 6]
                if len(digits) == 4 and all(c in _HEX_DIGITS for c in digits):
                    out.append(f"\\u{digits}")
                    i += 6
                    continue

            if nxt in _VALID_JSON_ESCAPES:
                out.append(f"\\{nxt}")
                i += 2
                continue

            out.append("\\\\")
            i += 1
            continue

        if _is_control_character(ch):
            out.append(_escape_control_character(ch))
        else:
            out.append(ch)
        i += 1

    return "".join(out)


def parse_json_with_repair(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        repaired = repair_json(text)
        if repaired != text:
            return json.loads(repaired)
        raise


def parse_streaming_json(partial: str | None) -> Any:
    """Best-effort parse of partial JSON. Always returns *something* (``{}``
    on total failure)."""

    if not partial or not partial.strip():
        return {}
    try:
        return parse_json_with_repair(partial)
    except Exception:
        pass

    if _partial_repair is not None:
        try:
            repaired = _partial_repair(partial)
            if isinstance(repaired, str):
                return json.loads(repaired) if repaired else {}
            return repaired or {}
        except Exception:
            pass
        try:
            repaired = _partial_repair(repair_json(partial))
            if isinstance(repaired, str):
                return json.loads(repaired) if repaired else {}
            return repaired or {}
        except Exception:
            pass

    return {}


__all__ = ["parse_json_with_repair", "parse_streaming_json", "repair_json"]
