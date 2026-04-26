"""Stable content fingerprints for memory deduplication."""

from __future__ import annotations

import hashlib


def normalize_content(content: str) -> str:
    """Normalize content before fingerprinting."""
    return " ".join(content.split()).strip().lower()


def content_fingerprint(content: str) -> str:
    """Return a SHA256 fingerprint for normalized memory content."""
    normalized = normalize_content(content)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
