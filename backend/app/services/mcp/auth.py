"""MCP OAuth Authentication - RFC 9728 Protected Resource Metadata.

Implements MCP authorization specification:
- Protected Resource Metadata (RFC 9728)
- Bearer token validation (RFC 6750)
- Scope-based access control

For Agent Hub, we support two authentication methods:
1. OAuth Bearer tokens (spec-compliant)
2. Agent Hub API keys (backward compatible)
"""

import logging
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.services.api_key_auth import (
    check_rate_limit,
    hash_api_key,
    update_key_last_used,
    validate_api_key,
)

logger = logging.getLogger(__name__)

# MCP scopes
MCP_SCOPE_COMPLETE = "mcp:complete"
MCP_SCOPE_CHAT = "mcp:chat"
MCP_SCOPE_TOOLS = "mcp:tools"
MCP_SCOPE_RESOURCES = "mcp:resources"
MCP_SCOPE_PROMPTS = "mcp:prompts"
MCP_SCOPE_ALL = "mcp:*"


@dataclass
class MCPProtectedResourceMetadata:
    """Protected Resource Metadata document (RFC 9728)."""

    authorization_servers: list[str]
    bearer_methods_supported: list[str] | None = None
    scopes_supported: list[str] | None = None

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        result = {"authorization_servers": self.authorization_servers}
        if self.bearer_methods_supported:
            result["bearer_methods_supported"] = self.bearer_methods_supported
        if self.scopes_supported:
            result["scopes_supported"] = self.scopes_supported
        return result


def get_protected_resource_metadata() -> MCPProtectedResourceMetadata:
    """Get the Protected Resource Metadata for this MCP server.

    In a full OAuth implementation, this would point to your OAuth
    authorization server. For Agent Hub, we support both:
    - External OAuth servers (configured via MCP_OAUTH_AUTHORIZATION_SERVERS)
    - Local API key authentication (Agent Hub keys)
    """
    # Default to local auth if no external OAuth configured
    auth_servers: list[str] = []

    # Check for configured external OAuth servers
    if hasattr(settings, "mcp_oauth_auth_servers") and settings.mcp_oauth_auth_servers:
        auth_servers = settings.mcp_oauth_auth_servers.split(",")
    else:
        # Default: point to our own auth endpoint
        auth_servers = [f"http://localhost:{settings.port}/api/api-keys"]

    return MCPProtectedResourceMetadata(
        authorization_servers=auth_servers,
        bearer_methods_supported=["header"],  # Only Authorization header supported
        scopes_supported=[
            MCP_SCOPE_COMPLETE,
            MCP_SCOPE_CHAT,
            MCP_SCOPE_TOOLS,
            MCP_SCOPE_RESOURCES,
            MCP_SCOPE_PROMPTS,
            MCP_SCOPE_ALL,
        ],
    )


def get_resource_metadata_uri() -> str:
    """Get the URI for our protected resource metadata."""
    # Use configured base URL or construct from settings
    base_url = getattr(settings, "mcp_base_url", f"http://localhost:{settings.port}")
    return f"{base_url}/.well-known/oauth-protected-resource"


def build_www_authenticate_header(
    error: str | None = None,
    error_description: str | None = None,
    scope: str | None = None,
) -> str:
    """Build WWW-Authenticate header per RFC 6750 and MCP spec."""
    parts = ["Bearer"]

    metadata_uri = get_resource_metadata_uri()
    parts.append(f'resource_metadata="{metadata_uri}"')

    if error:
        parts.append(f'error="{error}"')
    if error_description:
        parts.append(f'error_description="{error_description}"')
    if scope:
        parts.append(f'scope="{scope}"')

    return ", ".join(parts)


@dataclass
class MCPAuthResult:
    """Result of MCP authentication."""

    authenticated: bool
    key_id: int | None = None
    key_hash: str | None = None
    project_id: str | None = None
    scopes: list[str] | None = None
    rate_limit_rpm: int = 100
    rate_limit_tpm: int = 100000


async def validate_mcp_auth(
    authorization: Annotated[str | None, Header()] = None,
    db: Annotated[AsyncSession | None, Depends(get_db)] = None,
) -> MCPAuthResult | None:
    """Validate MCP authentication.

    Supports:
    1. Bearer tokens (Agent Hub API keys)
    2. Future: OAuth tokens from external auth servers

    Returns None if no auth provided (allows anonymous access if configured).
    Raises HTTPException if auth provided but invalid.
    """
    if not authorization:
        return None

    # Parse Bearer token
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Invalid authorization scheme",
            headers={
                "WWW-Authenticate": build_www_authenticate_header(
                    error="invalid_request",
                    error_description="Expected 'Bearer' authorization scheme",
                )
            },
        )

    token = authorization[7:]  # Remove "Bearer " prefix

    # Try Agent Hub API key validation first
    if token.startswith("sk-ah-") and db:
        key_record = await validate_api_key(db, token)
        if key_record:
            key_hash = hash_api_key(token)

            # Check rate limits
            is_allowed, error_msg = check_rate_limit(
                key_hash, key_record.rate_limit_rpm, key_record.rate_limit_tpm, 1000
            )
            if not is_allowed:
                raise HTTPException(
                    status_code=429,
                    detail=error_msg,
                    headers={
                        "WWW-Authenticate": build_www_authenticate_header(
                            error="rate_limit_exceeded", error_description=error_msg
                        )
                    },
                )

            await update_key_last_used(db, key_record.id)

            return MCPAuthResult(
                authenticated=True,
                key_id=key_record.id,
                key_hash=key_hash,
                project_id=key_record.project_id,
                scopes=[MCP_SCOPE_ALL],  # API keys get full access
                rate_limit_rpm=key_record.rate_limit_rpm,
                rate_limit_tpm=key_record.rate_limit_tpm,
            )

    # Extension point: External OAuth token validation
    # To add external OAuth providers (Auth0, Okta, etc.), validate JWT here:
    # 1. Fetch JWKS from authorization server
    # 2. Validate JWT signature and claims
    # 3. Check audience matches this server
    # 4. Extract scopes from token

    raise HTTPException(
        status_code=401,
        detail="Invalid or expired token",
        headers={
            "WWW-Authenticate": build_www_authenticate_header(
                error="invalid_token", error_description="The access token is invalid or expired"
            )
        },
    )


async def require_mcp_auth(
    authorization: Annotated[str | None, Header()] = None,
    db: Annotated[AsyncSession | None, Depends(get_db)] = None,
) -> MCPAuthResult:
    """FastAPI dependency requiring MCP authentication.

    Raises 401 if no valid authentication provided.
    """
    result = await validate_mcp_auth(authorization, db)
    if result is None:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={
                "WWW-Authenticate": build_www_authenticate_header(
                    error="invalid_request",
                    error_description="Authentication required to access MCP resources",
                )
            },
        )
    return result


def check_mcp_scope(auth: MCPAuthResult, required_scope: str) -> bool:
    """Check if authenticated user has required scope.

    Returns True if:
    - User has wildcard scope (mcp:*)
    - User has the exact required scope
    """
    if not auth.scopes:
        return False
    if MCP_SCOPE_ALL in auth.scopes:
        return True
    return required_scope in auth.scopes


def require_scope(required_scope: str):
    """Dependency factory for scope-based access control."""

    async def dependency(auth: MCPAuthResult = Depends(require_mcp_auth)) -> MCPAuthResult:
        if not check_mcp_scope(auth, required_scope):
            raise HTTPException(
                status_code=403,
                detail=f"Insufficient scope. Required: {required_scope}",
                headers={
                    "WWW-Authenticate": build_www_authenticate_header(
                        error="insufficient_scope",
                        error_description=f"Required scope: {required_scope}",
                        scope=required_scope,
                    )
                },
            )
        return auth

    return dependency
