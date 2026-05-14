"""Shared PKCE helpers for OAuth flows."""

from __future__ import annotations

import base64
import hashlib
import os


def generate_pkce() -> tuple[str, str]:
    """Generate a PKCE code verifier and S256 code challenge.

    Returns:
        (code_verifier, code_challenge)
    """
    verifier_bytes = os.urandom(32)
    code_verifier = base64.urlsafe_b64encode(verifier_bytes).rstrip(b"=").decode("ascii")
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge
