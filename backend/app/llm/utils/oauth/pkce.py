"""PKCE (Proof Key for Code Exchange) utilities.

Direct port of pi-mono ``utils/oauth/pkce.ts``. Uses ``secrets`` for entropy
and the stdlib SHA-256 — the same RFC 7636 S256 challenge transform.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass


def _base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def generate_code_verifier(num_bytes: int = 32) -> str:
    """Return a 32-byte PKCE code verifier as base64url."""
    return _base64url_encode(secrets.token_bytes(num_bytes))


def generate_code_challenge(verifier: str) -> str:
    """Return the S256 code challenge for ``verifier``."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return _base64url_encode(digest)


@dataclass(slots=True)
class PKCEPair:
    verifier: str
    challenge: str


def generate_pkce() -> PKCEPair:
    """Generate a PKCE verifier/challenge pair (S256)."""
    verifier = generate_code_verifier()
    return PKCEPair(verifier=verifier, challenge=generate_code_challenge(verifier))


__all__ = [
    "PKCEPair",
    "generate_code_challenge",
    "generate_code_verifier",
    "generate_pkce",
]
