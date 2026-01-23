"""Client authentication service for access control.

Provides:
- Client registration with cryptographic secret generation
- Secret verification using bcrypt
- Client status management (active, suspended, blocked)
- Secret rotation
"""

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import bcrypt
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Client

# Client secret prefix for Agent Hub clients
SECRET_PREFIX = "ahc_"


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


def generate_client_secret() -> tuple[str, str, str]:
    """Generate a new client secret.

    Returns:
        Tuple of (full_secret, secret_hash, secret_prefix)
        - full_secret: Show once to user (ahc_ + 40 random chars)
        - secret_hash: bcrypt hash for storage
        - secret_prefix: For display (ahc_ + first 8 chars)
    """
    random_part = secrets.token_urlsafe(30)  # ~40 chars
    full_secret = f"{SECRET_PREFIX}{random_part}"
    secret_hash = bcrypt.hashpw(full_secret.encode(), bcrypt.gensalt()).decode()
    secret_prefix = f"{SECRET_PREFIX}{random_part[:8]}"
    return full_secret, secret_hash, secret_prefix


def verify_secret(secret: str, secret_hash: str) -> bool:
    """Verify a secret against its bcrypt hash."""
    try:
        return bcrypt.checkpw(secret.encode(), secret_hash.encode())
    except Exception:
        return False


class ClientAuthService:
    """Service for client authentication and management."""

    def __init__(self, db: AsyncSession):
        self.db = db

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

    async def suspend_client(self, client_id: str, reason: str, suspended_by: str) -> bool:
        """Suspend a client (temporary block).

        Args:
            client_id: The client UUID
            reason: Reason for suspension
            suspended_by: Who suspended the client

        Returns:
            True if suspended, False if client not found
        """
        result = await self.db.execute(select(Client).where(Client.id == client_id))
        client = result.scalar_one_or_none()

        if not client:
            return False

        await self.db.execute(
            update(Client)
            .where(Client.id == client_id)
            .values(
                status="suspended",
                suspended_at=datetime.now(UTC),
                suspended_by=suspended_by,
                suspension_reason=reason,
                updated_at=datetime.now(UTC),
            )
        )
        await self.db.commit()
        return True

    async def activate_client(self, client_id: str) -> bool:
        """Activate a suspended client.

        Args:
            client_id: The client UUID

        Returns:
            True if activated, False if client not found
        """
        result = await self.db.execute(select(Client).where(Client.id == client_id))
        client = result.scalar_one_or_none()

        if not client:
            return False

        await self.db.execute(
            update(Client)
            .where(Client.id == client_id)
            .values(
                status="active",
                suspended_at=None,
                suspended_by=None,
                suspension_reason=None,
                updated_at=datetime.now(UTC),
            )
        )
        await self.db.commit()
        return True

    async def block_client(self, client_id: str, reason: str, blocked_by: str) -> bool:
        """Block a client permanently.

        Args:
            client_id: The client UUID
            reason: Reason for blocking
            blocked_by: Who blocked the client

        Returns:
            True if blocked, False if client not found
        """
        result = await self.db.execute(select(Client).where(Client.id == client_id))
        client = result.scalar_one_or_none()

        if not client:
            return False

        await self.db.execute(
            update(Client)
            .where(Client.id == client_id)
            .values(
                status="blocked",
                suspended_at=datetime.now(UTC),
                suspended_by=blocked_by,
                suspension_reason=reason,
                updated_at=datetime.now(UTC),
            )
        )
        await self.db.commit()
        return True
