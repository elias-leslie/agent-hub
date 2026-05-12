"""OAuth flow endpoints for Claude and Codex providers.

Handles the browser-based OAuth PKCE flow:
1. Frontend calls POST /api/oauth/{provider}/authorize
2. Backend generates PKCE params, starts temp callback server (Codex),
   returns auth URL
3. Frontend opens auth URL in popup AND shows manual paste input
4. **Local path**: callback server receives redirect -> tokens stored -> popup
   does postMessage("oauth-success") -> frontend clears paste UI
5. **Remote path** (or Claude): user copies code/URL -> pastes into input ->
   frontend calls POST /api/oauth/{provider}/exchange -> tokens stored
6. Whichever path completes first wins; the other is cancelled/cleaned up.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.claude_auth import create_claude_auth_flow
from app.adapters.codex_auth import create_auth_flow as create_codex_auth_flow
from app.api.oauth_exchange import exchange_claude, exchange_codex
from app.api.oauth_flows import complete_codex_flow
from app.api.oauth_schemas import (
    OAuthAuthorizeResponse,
    OAuthExchangeRequest,
    OAuthExchangeResponse,
    OAuthStatusResponse,
)
from app.api.oauth_status import check_claude_token_status, check_codex_token_status
from app.api.oauth_store import (
    cancel_active_server,
    cleanup_expired_flows,
    get_pending_flow,
    pop_pending_flow,
    set_pending_flow,
    spawn_background_task,
)
from app.db import get_db
from app.services.credential_manager import get_credential_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/oauth", tags=["oauth"])

_SUPPORTED_PROVIDERS = frozenset({"claude", "codex"})


# ---------------------------------------------------------------------------
# Authorize endpoints
# ---------------------------------------------------------------------------


@router.post("/codex/authorize", response_model=OAuthAuthorizeResponse)
async def authorize_codex(db: Annotated[AsyncSession, Depends(get_db)]) -> OAuthAuthorizeResponse:
    """Start Codex OAuth PKCE flow; backend starts a local callback server."""
    cleanup_expired_flows()
    cancel_active_server("codex")
    flow = create_codex_auth_flow()
    set_pending_flow(flow["state"], "codex", flow["code_verifier"])
    spawn_background_task(complete_codex_flow(flow["state"], db))
    return OAuthAuthorizeResponse(url=flow["url"], state=flow["state"], uses_callback_server=True)


@router.post("/claude/authorize", response_model=OAuthAuthorizeResponse)
async def authorize_claude() -> OAuthAuthorizeResponse:
    """Start Claude OAuth PKCE flow (no local callback server needed)."""
    cleanup_expired_flows()
    flow = create_claude_auth_flow()
    set_pending_flow(flow["state"], "claude", flow["code_verifier"])
    return OAuthAuthorizeResponse(url=flow["url"], state=flow["state"], uses_callback_server=False)


# ---------------------------------------------------------------------------
# Status endpoint
# ---------------------------------------------------------------------------


@router.get("/{provider}/status", response_model=OAuthStatusResponse)
async def get_oauth_status(
    provider: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OAuthStatusResponse:
    """Check OAuth authentication status for a provider."""
    if provider not in _SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"OAuth not supported for provider: {provider}")

    from app.api.preferences import get_preference_value

    cm = get_credential_manager()
    api_key_status = "configured" if cm.get_api_key(provider) else "not_configured"

    if provider == "claude":
        oauth_status, email = check_claude_token_status()
    else:
        oauth_status, email = check_codex_token_status()

    preferred_auth = await get_preference_value(db, f"{provider}_auth_preference", "api_key")

    return OAuthStatusResponse(
        provider=provider,
        oauth_status=oauth_status,
        api_key_status=api_key_status,
        preferred_auth=preferred_auth,
        email=email,
    )


# ---------------------------------------------------------------------------
# Manual exchange endpoint
# ---------------------------------------------------------------------------


@router.post("/{provider}/exchange", response_model=OAuthExchangeResponse)
async def exchange_oauth_code(
    provider: str,
    body: OAuthExchangeRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OAuthExchangeResponse:
    """Manually exchange an OAuth code/URL for tokens.

    Used when the local callback server is unreachable (remote access)
    or for Claude (which never has a callback server).
    """
    if provider not in _SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Exchange not supported for provider: {provider}")

    flow = get_pending_flow(body.state)
    if not flow:
        return OAuthExchangeResponse(success=False, provider=provider, error="Unknown or expired state")
    if flow["provider"] != provider:
        return OAuthExchangeResponse(success=False, provider=provider, error="State/provider mismatch")

    code_verifier = str(flow["code_verifier"])
    cancel_active_server(provider)

    try:
        if provider == "claude":
            email = await exchange_claude(body, code_verifier, db)
        else:
            email = await exchange_codex(body, code_verifier, db)

        from app.routing.registry import invalidate as invalidate_adapter

        invalidate_adapter(provider)
        logger.info("Manual OAuth exchange succeeded for %s", provider)
        pop_pending_flow(body.state)
        return OAuthExchangeResponse(success=True, provider=provider, email=email)

    except Exception as e:
        logger.exception("Manual OAuth exchange failed for %s", provider)
        return OAuthExchangeResponse(success=False, provider=provider, error=str(e))
