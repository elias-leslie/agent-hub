"""Codex safety-refusal codes and reroute reasons, shared by the Responses provider and the native runtime."""

from __future__ import annotations

# Keys are lower-cased with underscores removed, so cyberPolicy and cyber_policy match.
_REFUSAL_CATEGORIES = {
    "cyberpolicy": "cyber",
    "biopolicy": "bio",
    "misalignmentpolicyviolation": "misalignment",
    "toomanydenials": "too_many_denials",
}
_REROUTE_CATEGORIES = {"highriskcyberactivity": "cyber"}


def _normal(value: object) -> str:
    return str(value).replace("_", "").replace("-", "").lower() if value is not None else ""


def codex_refusal_category(code: object) -> str | None:
    """Safety category for a Codex error code, or None when the code is not a refusal."""

    return _REFUSAL_CATEGORIES.get(_normal(code))


def reroute_category(reason: object) -> str | None:
    """Safety category for a ``model/rerouted`` reason; unknown reasons keep their own text."""

    if not isinstance(reason, str) or not reason.strip():
        return None
    return _REROUTE_CATEGORIES.get(_normal(reason), reason.strip())
