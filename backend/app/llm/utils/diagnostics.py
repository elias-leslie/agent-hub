"""Diagnostic-payload helpers (port of pi-mono ``utils/diagnostics.ts``).

Used by providers to surface redacted error/recovery information on
``AssistantMessage.diagnostics``. The dataclass shape matches pi-mono's
``AssistantMessageDiagnostic`` so persisted history diffs cleanly.
"""

from __future__ import annotations

import time
import traceback
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class DiagnosticErrorInfo:
    message: str
    name: str | None = None
    stack: str | None = None
    code: str | int | None = None


@dataclass(slots=True)
class AssistantMessageDiagnostic:
    type: str
    timestamp: int  # Unix ms
    error: DiagnosticErrorInfo | None = None
    details: dict[str, Any] | None = None


def format_thrown_value(value: Any) -> str:
    if isinstance(value, BaseException):
        return str(value) or type(value).__name__
    if isinstance(value, str):
        return value
    return str(value)


def extract_diagnostic_error(error: Any) -> DiagnosticErrorInfo:
    if not isinstance(error, BaseException):
        return DiagnosticErrorInfo(name="ThrownValue", message=format_thrown_value(error))
    name = type(error).__name__
    msg = str(error) or name
    stack: str | None = None
    if error.__traceback__ is not None:
        stack = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    code: str | int | None = None
    raw_code = getattr(error, "code", None)
    if isinstance(raw_code, (str, int)):
        code = raw_code
    return DiagnosticErrorInfo(name=name, message=msg, stack=stack, code=code)


def create_assistant_message_diagnostic(
    type: str,
    error: Any,
    details: dict[str, Any] | None = None,
) -> AssistantMessageDiagnostic:
    return AssistantMessageDiagnostic(
        type=type,
        timestamp=int(time.time() * 1000),
        error=extract_diagnostic_error(error),
        details=details,
    )


def append_assistant_message_diagnostic(
    message: Any,
    diagnostic: AssistantMessageDiagnostic,
) -> None:
    """Append ``diagnostic`` to ``message.diagnostics``; initialize the list if absent."""

    existing = getattr(message, "diagnostics", None) or []
    message.diagnostics = [*existing, diagnostic]


__all__ = [
    "AssistantMessageDiagnostic",
    "DiagnosticErrorInfo",
    "append_assistant_message_diagnostic",
    "create_assistant_message_diagnostic",
    "extract_diagnostic_error",
    "format_thrown_value",
]
