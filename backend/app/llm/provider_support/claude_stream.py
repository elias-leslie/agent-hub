"""Claude Code CLI stream-json events, read into typed provider outcomes.

One observer serves every caller of the headless CLI (the ``claude-code-cli`` provider and workflow step
executors), so refusal, substitution and usage-limit detection live in one place. It only reads protocol
fields of the event stream; it never touches credentials.
"""

from __future__ import annotations

import re
from typing import Any

from ..utils.outcomes import ProviderOutcome, is_model_switch

SYNTHETIC_MODEL = "<synthetic>"
_REFUSAL_TEXT = re.compile(r"safeguards (?:flagged|stopped)|can.t help with this", re.IGNORECASE)
_REFUSAL_CATEGORY = re.compile(r"Details: `\[(\w+)\]`")


def rate_limit_message(info: dict[str, Any]) -> str | None:
    status = str(info.get("status") or "")
    if status in ("", "allowed", "allowed_warning"):
        return None
    window = info.get("rateLimitType") or "subscription"
    resets_at = info.get("resetsAt")
    reset = f"; resets at unix {resets_at}" if resets_at else ""
    return f"429 rate limit: Claude {window} usage limit reached ({status}){reset}"


def substituted_text(requested: str, served: str | None, category: str | None) -> str:
    why = f" after a {category} safeguard flag" if category else ""
    return f"Claude Code CLI served {served or 'another model'} instead of {requested}{why}; the requested model did not answer"


def result_error(result: dict[str, Any] | None, returncode: int | None, stderr: str) -> str | None:
    if result is not None and not result.get("is_error") and result.get("subtype") == "success":
        return None
    detail = ""
    if result is not None:
        detail = str(result.get("result") or "; ".join(map(str, result.get("errors") or [])) or result.get("subtype") or "")
    detail = detail or stderr.strip()[-2_000:] or f"exit status {returncode}"
    lowered = detail.lower()
    if "not logged in" in lowered or "/login" in lowered or ("oauth" in lowered and "expired" in lowered):
        return f"401 unauthorized: Claude Code CLI is not signed in ({detail})"
    if "issue with the selected model" in lowered:
        return f"model_not_found: {detail}"
    return f"Claude Code CLI failed: {detail}"


class ClaudeTurnObserver:
    """Accumulates what one CLI turn says about who answered it and why it ended."""

    def __init__(self) -> None:
        self.rate_limit_info: dict[str, Any] | None = None
        self.result: dict[str, Any] | None = None
        self.served: set[str] = set()
        self.refusal: dict[str, Any] | None = None
        self.fallback: dict[str, Any] | None = None
        self.answer_text: list[str] = []

    def handle(self, event: dict[str, Any]) -> None:
        kind = event.get("type")
        if kind == "assistant":
            self._assistant(event)
        elif kind == "system":
            self._system(event)
        elif kind == "rate_limit_event":
            info = event.get("rate_limit_info") or {}
            if rate_limit_message(info):
                self.rate_limit_info = info
        elif kind == "result":
            self._result(event)

    def _result(self, event: dict[str, Any]) -> None:
        self.result = event
        self.served.update(k for k in (event.get("modelUsage") or {}) if k != SYNTHETIC_MODEL)
        if (
            event.get("stop_reason") == "refusal"
            or "refus" in str(event.get("terminal_reason") or "")
            or (event.get("safety_stops") or 0) > 0
            or (event.get("is_error") and _REFUSAL_TEXT.search(str(event.get("result") or "")))
        ):
            self._note_refusal(str(event.get("result") or ""), None, None, None)

    def _note_refusal(self, text: str, category: str | None, explanation: str | None, request_id: str | None) -> None:
        match = _REFUSAL_CATEGORY.search(text)
        current = self.refusal or {}
        self.refusal = {
            "category": category or (match.group(1) if match else None) or current.get("category"),
            "explanation": explanation or current.get("explanation"),
            "request_id": request_id or current.get("request_id"),
        }

    def _assistant(self, event: dict[str, Any]) -> None:
        message = event.get("message") or {}
        name = message.get("model")
        if name and name != SYNTHETIC_MODEL:
            self.served.add(str(name))
        text = "\n".join(
            str(block.get("text") or "") for block in message.get("content") or [] if block.get("type") == "text"
        )
        details = message.get("stop_details") or {}
        if (
            message.get("stop_reason") == "refusal"
            or details.get("type") == "refusal"
            or (name == SYNTHETIC_MODEL and _REFUSAL_TEXT.search(text))
        ):
            self._note_refusal(text, details.get("category"), details.get("explanation"), event.get("request_id"))
        elif name != SYNTHETIC_MODEL and text:
            self.answer_text.append(text)

    def _system(self, event: dict[str, Any]) -> None:
        subtype = event.get("subtype")
        if subtype == "model_refusal_fallback":
            self.fallback = event
        elif subtype == "informational" and _REFUSAL_TEXT.search(str(event.get("content") or "")):
            self._note_refusal(str(event.get("content")), None, None, None)

    def succeeded(self) -> bool:
        return self.result is not None and not self.result.get("is_error") and self.result.get("subtype") == "success"

    def outcome(self, requested: str) -> tuple[ProviderOutcome, str] | None:
        """Classify a refusal, substitution or usage limit, with the error text for it."""
        if self.fallback is not None:
            fb = self.fallback
            served = fb.get("fallbackModel")
            return ProviderOutcome(
                kind="substituted", requested_model=requested, served_model=served,
                category=fb.get("apiRefusalCategory"), explanation=fb.get("apiRefusalExplanation"),
                request_id=fb.get("requestId"),
            ), substituted_text(requested, served, fb.get("apiRefusalCategory"))
        if self.refusal is not None:
            category = self.refusal["category"]
            label = f" ({category})" if category else ""
            return ProviderOutcome(
                kind="refused", requested_model=requested, category=category,
                explanation=self.refusal["explanation"], request_id=self.refusal["request_id"],
            ), f"Claude refused the request: safeguards flagged it{label}; {requested} did not answer"
        other = sorted(name for name in self.served if is_model_switch(requested, name))
        if other:
            return ProviderOutcome(kind="substituted", requested_model=requested, served_model=other[0]), (
                substituted_text(requested, other[0], None)
            )
        if self.rate_limit_info is not None and not self.succeeded():
            info = self.rate_limit_info
            return ProviderOutcome(
                kind="usage_limit", requested_model=requested,
                window=info.get("rateLimitType"), resets_at=info.get("resetsAt"),
            ), rate_limit_message(info) or "Claude usage limit reached"
        return None
