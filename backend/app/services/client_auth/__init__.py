"""Client authentication service for access control.

Provides:
- Client registration with cryptographic secret generation
- Secret verification using bcrypt with caching
- Client status management (active, suspended, blocked)
- Secret rotation
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Client

from .secret_utils import generate_client_secret, verify_secret
from .status_manager import ClientStatusManager

# Re-export for backward compatibility
__all__ = [
    "AuthenticatedClient",
    "ClientAuthService",
    "ClientRegistration",
    "verify_secret",
]


@dataclass
class ClientRegistration:
    """Result of client registration with the one-time secret."""

    client_id: str
    display_name: str
    secret: str  # Full secret - show only once
    secret_prefix: str  # For display: "ahc_" + first 8 chars


@dataclass
class AuthenticatedClient:
    """Result of successful client authentication."""

    client_id: str
    display_name: str
    client_type: str
    status: str
    rate_limit_rpm: int
    rate_limit_tpm: int


class ClientAuthService:
    """Service for client authentication and management."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self._status_manager = ClientStatusManager(db)

    async def register_client(
        self,
        display_name: str,
        client_type: str = "external",
        rate_limit_rpm: int = 60,
        rate_limit_tpm: int = 100000,
    ) -> ClientRegistration:
        """Register a new client and return the one-time secret.

        Args:
            display_name: Human-readable name for the client
            client_type: One of "internal", "external", "service"
            rate_limit_rpm: Requests per minute limit
            rate_limit_tpm: Tokens per minute limit

        Returns:
            ClientRegistration with the full secret (show only once)
        """
        client_id = str(uuid.uuid4())
        full_secret, secret_hash, secret_prefix = generate_client_secret()

        client = Client(
            id=client_id,
            display_name=display_name,
            client_type=client_type,
            secret_hash=secret_hash,
            secret_prefix=secret_prefix,
            status="active",
            rate_limit_rpm=rate_limit_rpm,
            rate_limit_tpm=rate_limit_tpm,
        )

        self.db.add(client)
        await self.db.commit()

        return ClientRegistration(
            client_id=client_id,
            display_name=display_name,
            secret=full_secret,
            secret_prefix=secret_prefix,
        )

    async def authenticate(self, client_id: str, client_secret: str) -> AuthenticatedClient | None:
        """Authenticate a client by ID and secret.

        Args:
            client_id: The client UUID
            client_secret: The client secret (ahc_...)

        Returns:
            AuthenticatedClient if valid, None if authentication fails
        """
        result = await self.db.execute(select(Client).where(Client.id == client_id))
        client = result.scalar_one_or_none()

        if not client:
            return None

        # Verify the secret
        if not verify_secret(client_secret, client.secret_hash):
            return None

        # Check status - only active clients can authenticate
        if client.status != "active":
            return None

        # Update last_used_at
        await self.db.execute(
            update(Client).where(Client.id == client_id).values(last_used_at=datetime.now(UTC))
        )
        await self.db.commit()

        return AuthenticatedClient(
            client_id=client.id,
            display_name=client.display_name,
            client_type=client.client_type,
            status=client.status,
            rate_limit_rpm=client.rate_limit_rpm,
            rate_limit_tpm=client.rate_limit_tpm,
        )

    async def rotate_secret(self, client_id: str) -> str | None:
        """Generate a new secret for a client.

        Args:
            client_id: The client UUID

        Returns:
            New full secret if successful, None if client not found
        """
        result = await self.db.execute(select(Client).where(Client.id == client_id))
        client = result.scalar_one_or_none()

        if not client:
            return None

        full_secret, secret_hash, secret_prefix = generate_client_secret()

        await self.db.execute(
            update(Client)
            .where(Client.id == client_id)
            .values(
                secret_hash=secret_hash,
                secret_prefix=secret_prefix,
                updated_at=datetime.now(UTC),
            )
        )
        await self.db.commit()

        return full_secret

    async def get_client(self, client_id: str) -> Client | None:
        """Get a client by ID."""
        result = await self.db.execute(select(Client).where(Client.id == client_id))
        return result.scalar_one_or_none()

    # Delegate status management to status_manager
    async def suspend_client(self, client_id: str, reason: str, suspended_by: str) -> bool:
        """Suspend a client (temporary block)."""
        return await self._status_manager.suspend_client(client_id, reason, suspended_by)

    async def activate_client(self, client_id: str) -> bool:
        """Activate a suspended client."""
        return await self._status_manager.activate_client(client_id)

    async def block_client(self, client_id: str, reason: str, blocked_by: str) -> bool:
        """Block a client permanently."""
        return await self._status_manager.block_client(client_id, reason, blocked_by)
