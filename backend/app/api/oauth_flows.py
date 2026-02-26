"""Background OAuth flow completion tasks for each provider."""

from __future__ import annotations

import json
import logging
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.codex_auth import CODEX_REDIRECT_URI
from app.adapters.codex_auth import exchange_code as exchange_codex_code
from app.adapters.gemini_auth import (
    ANTIGRAVITY_REDIRECT_URI,
    GEMINI_REDIRECT_URI,
    discover_project,
    exchange_antigravity_code,
    exchange_gemini_code,
    get_user_email,
)
from app.api.oauth_callback import run_callback_flow
from app.api.oauth_store import get_pending_flow, pop_pending_flow, upsert_credential

logger = logging.getLogger(__name__)


async def _store_google_token(
    db: AsyncSession,
    provider: str,
    access_token: str,
    refresh_token: str | None,
    expires_at: float | None,
) -> None:
    """Discover project/email and persist a Google-style token blob."""
    project_id = await discover_project(access_token)
    email = await get_user_email(access_token)
    token_data = json.dumps(
        {"access_token": access_token, "project_id": project_id, "email": email, "expires_at": expires_at}
    )
    await upsert_credential(db, provider, "oauth_token", token_data)
    if refresh_token:
        await upsert_credential(db, provider, "refresh_token", refresh_token)
    logger.info("OAuth flow completed for %s (project=%s, email=%s)", provider, project_id, email)


async def complete_codex_flow(state: str, db: AsyncSession) -> None:
    """Wait for Codex OAuth callback, exchange code, store credentials."""
    parsed = urlparse(CODEX_REDIRECT_URI)
    port = parsed.port or 1455
    path = parsed.path

    try:
        code, received_state = await run_callback_flow(port, path, "codex")

        if received_state != state:
            logger.error("Codex OAuth state mismatch")
            return

        flow = get_pending_flow(state)
        if not flow:
            logger.error("Codex OAuth flow not found for state")
            return

        creds = await exchange_codex_code(code, str(flow["code_verifier"]))
        await upsert_credential(db, "codex", "oauth_token", creds.access_token)
        if creds.refresh_token:
            await upsert_credential(db, "codex", "refresh_token", creds.refresh_token)
        logger.info("Codex OAuth flow completed successfully")

    except Exception:
        logger.exception("Codex OAuth flow failed")
    finally:
        pop_pending_flow(state)


async def complete_gemini_flow(state: str, db: AsyncSession) -> None:
    """Wait for Gemini OAuth callback, exchange code, store credentials."""
    parsed = urlparse(GEMINI_REDIRECT_URI)
    port = parsed.port or 8085
    path = parsed.path

    try:
        code, received_state = await run_callback_flow(port, path, "gemini")

        if received_state != state:
            logger.error("Gemini OAuth state mismatch")
            return

        flow = get_pending_flow(state)
        if not flow:
            logger.error("Gemini OAuth flow not found for state")
            return

        creds = await exchange_gemini_code(code, str(flow["code_verifier"]))
        await _store_google_token(db, "gemini", creds.access_token, creds.refresh_token, creds.expires_at)

    except Exception:
        logger.exception("Gemini OAuth flow failed")
    finally:
        pop_pending_flow(state)


async def complete_antigravity_flow(state: str, db: AsyncSession) -> None:
    """Wait for Antigravity OAuth callback, exchange code, store credentials."""
    parsed = urlparse(ANTIGRAVITY_REDIRECT_URI)
    port = parsed.port or 51121
    path = parsed.path

    try:
        code, received_state = await run_callback_flow(port, path, "antigravity")

        if received_state != state:
            logger.error("Antigravity OAuth state mismatch")
            return

        flow = get_pending_flow(state)
        if not flow:
            logger.error("Antigravity OAuth flow not found for state")
            return

        creds = await exchange_antigravity_code(code, str(flow["code_verifier"]))
        await _store_google_token(
            db, "antigravity", creds.access_token, creds.refresh_token, creds.expires_at
        )

    except Exception:
        logger.exception("Antigravity OAuth flow failed")
    finally:
        pop_pending_flow(state)
