"""Tests for MCP OAuth authentication."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.mcp.auth import (
    MCP_SCOPE_ALL,
    MCP_SCOPE_TOOLS,
    MCPAuthResult,
    MCPProtectedResourceMetadata,
    build_www_authenticate_header,
    check_mcp_scope,
    get_protected_resource_metadata,
    require_mcp_auth,
    require_scope,
    validate_mcp_auth,
)


class TestMCPProtectedResourceMetadata:
    """Tests for Protected Resource Metadata."""

    def test_create_metadata(self):
        """Test creating metadata object."""
        metadata = MCPProtectedResourceMetadata(
            authorization_servers=["https://auth.example.com"],
            bearer_methods_supported=["header"],
            scopes_supported=["mcp:tools", "mcp:*"],
        )

        assert metadata.authorization_servers == ["https://auth.example.com"]
        assert metadata.bearer_methods_supported == ["header"]
        assert metadata.scopes_supported == ["mcp:tools", "mcp:*"]

    def test_to_dict(self):
        """Test converting to dictionary."""
        metadata = MCPProtectedResourceMetadata(
            authorization_servers=["https://auth.example.com"],
        )

        result = metadata.to_dict()

        assert "authorization_servers" in result
        assert result["authorization_servers"] == ["https://auth.example.com"]

    def test_to_dict_excludes_none(self):
        """Test that None values are excluded from dict."""
        metadata = MCPProtectedResourceMetadata(
            authorization_servers=["https://auth.example.com"],
        )

        result = metadata.to_dict()

        assert "bearer_methods_supported" not in result
        assert "scopes_supported" not in result


class TestGetProtectedResourceMetadata:
    """Tests for get_protected_resource_metadata function."""

    def test_returns_metadata(self):
        """Test that function returns valid metadata."""
        metadata = get_protected_resource_metadata()

        assert isinstance(metadata, MCPProtectedResourceMetadata)
        assert len(metadata.authorization_servers) >= 1
        assert metadata.scopes_supported is not None

    def test_with_configured_oauth_servers(self):
        """Test metadata with configured OAuth servers."""
        with patch("app.services.mcp.auth.settings") as mock_settings:
            mock_settings.mcp_oauth_auth_servers = (
                "https://auth1.example.com,https://auth2.example.com"
            )
            mock_settings.port = 8003

            metadata = get_protected_resource_metadata()

            assert len(metadata.authorization_servers) == 2
            assert "https://auth1.example.com" in metadata.authorization_servers


class TestBuildWWWAuthenticateHeader:
    """Tests for WWW-Authenticate header building."""

    def test_basic_header(self):
        """Test building basic header."""
        with patch("app.services.mcp.auth.get_resource_metadata_uri") as mock_uri:
            mock_uri.return_value = "https://example.com/.well-known/oauth-protected-resource"

            header = build_www_authenticate_header()

            assert "Bearer" in header
            assert "resource_metadata=" in header

    def test_header_with_error(self):
        """Test header with error info."""
        with patch("app.services.mcp.auth.get_resource_metadata_uri") as mock_uri:
            mock_uri.return_value = "https://example.com/.well-known/oauth-protected-resource"

            header = build_www_authenticate_header(
                error="invalid_token", error_description="Token expired"
            )

            assert 'error="invalid_token"' in header
            assert 'error_description="Token expired"' in header

    def test_header_with_scope(self):
        """Test header with scope."""
        with patch("app.services.mcp.auth.get_resource_metadata_uri") as mock_uri:
            mock_uri.return_value = "https://example.com/.well-known/oauth-protected-resource"

            header = build_www_authenticate_header(scope="mcp:tools mcp:resources")

            assert 'scope="mcp:tools mcp:resources"' in header


class TestValidateMCPAuth:
    """Tests for validate_mcp_auth function."""

    @pytest.mark.asyncio
    async def test_no_auth_returns_none(self):
        """Test that no authorization returns None."""
        result = await validate_mcp_auth(authorization=None, db=None)
        assert result is None

    @pytest.mark.asyncio
    async def test_invalid_scheme_raises(self):
        """Test that non-Bearer scheme raises HTTPException."""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await validate_mcp_auth(authorization="Basic abc123", db=None)

        assert exc_info.value.status_code == 401
        assert "WWW-Authenticate" in exc_info.value.headers

    @pytest.mark.asyncio
    async def test_valid_api_key(self):
        """Test validation with valid Agent Hub API key."""
        mock_key_record = MagicMock()
        mock_key_record.id = 1
        mock_key_record.project_id = "test-project"
        mock_key_record.rate_limit_rpm = 100
        mock_key_record.rate_limit_tpm = 100000

        mock_db = AsyncMock()

        with patch("app.services.mcp.auth.validate_api_key") as mock_validate:
            mock_validate.return_value = mock_key_record

            with patch("app.services.mcp.auth.check_rate_limit") as mock_rate:
                mock_rate.return_value = (True, None)

                with patch("app.services.mcp.auth.update_key_last_used") as mock_update:
                    mock_update.return_value = None

                    result = await validate_mcp_auth(
                        authorization="Bearer sk-ah-testkey123", db=mock_db
                    )

                    assert result is not None
                    assert result.authenticated is True
                    assert MCP_SCOPE_ALL in result.scopes

    @pytest.mark.asyncio
    async def test_rate_limited_raises(self):
        """Test that rate limited key raises HTTPException."""
        from fastapi import HTTPException

        mock_key_record = MagicMock()
        mock_key_record.id = 1
        mock_key_record.rate_limit_rpm = 100
        mock_key_record.rate_limit_tpm = 100000

        mock_db = AsyncMock()

        with patch("app.services.mcp.auth.validate_api_key") as mock_validate:
            mock_validate.return_value = mock_key_record

            with patch("app.services.mcp.auth.check_rate_limit") as mock_rate:
                mock_rate.return_value = (False, "Rate limit exceeded")

                with pytest.raises(HTTPException) as exc_info:
                    await validate_mcp_auth(authorization="Bearer sk-ah-testkey123", db=mock_db)

                assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_invalid_token_raises(self):
        """Test that invalid token raises HTTPException."""
        from fastapi import HTTPException

        mock_db = AsyncMock()

        with patch("app.services.mcp.auth.validate_api_key") as mock_validate:
            mock_validate.return_value = None

            with pytest.raises(HTTPException) as exc_info:
                await validate_mcp_auth(authorization="Bearer invalid-token", db=mock_db)

            assert exc_info.value.status_code == 401


class TestRequireMCPAuth:
    """Tests for require_mcp_auth dependency."""

    @pytest.mark.asyncio
    async def test_raises_without_auth(self):
        """Test that missing auth raises HTTPException."""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await require_mcp_auth(authorization=None, db=None)

        assert exc_info.value.status_code == 401


class TestCheckMCPScope:
    """Tests for scope checking."""

    def test_wildcard_scope_allows_all(self):
        """Test that wildcard scope grants all access."""
        auth = MCPAuthResult(authenticated=True, scopes=[MCP_SCOPE_ALL])

        assert check_mcp_scope(auth, MCP_SCOPE_TOOLS) is True
        assert check_mcp_scope(auth, "mcp:anything") is True

    def test_exact_scope_match(self):
        """Test that exact scope match works."""
        auth = MCPAuthResult(authenticated=True, scopes=[MCP_SCOPE_TOOLS])

        assert check_mcp_scope(auth, MCP_SCOPE_TOOLS) is True
        assert check_mcp_scope(auth, "mcp:resources") is False

    def test_no_scopes_denies_all(self):
        """Test that no scopes denies access."""
        auth = MCPAuthResult(authenticated=True, scopes=None)

        assert check_mcp_scope(auth, MCP_SCOPE_TOOLS) is False


class TestRequireScope:
    """Tests for require_scope dependency factory."""

    @pytest.mark.asyncio
    async def test_allows_valid_scope(self):
        """Test that valid scope is allowed."""
        auth = MCPAuthResult(authenticated=True, scopes=[MCP_SCOPE_ALL])

        dependency = require_scope(MCP_SCOPE_TOOLS)

        # Mock the require_mcp_auth to return our auth
        with patch("app.services.mcp.auth.require_mcp_auth") as mock_require:
            mock_require.return_value = auth

            # Manually call the dependency with auth
            result = await dependency(auth)
            assert result is auth

    @pytest.mark.asyncio
    async def test_denies_missing_scope(self):
        """Test that missing scope is denied."""
        from fastapi import HTTPException

        auth = MCPAuthResult(authenticated=True, scopes=["mcp:other"])

        dependency = require_scope(MCP_SCOPE_TOOLS)

        with pytest.raises(HTTPException) as exc_info:
            await dependency(auth)

        assert exc_info.value.status_code == 403
        assert "insufficient_scope" in exc_info.value.headers.get("WWW-Authenticate", "")
