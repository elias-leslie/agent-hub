"""Client registration and identification service.

Provides:
- Client registration with UUID generation
- Client identification by ID (no secret verification)
- Client status management (active, suspended, blocked)
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Client

from .status_manager import ClientStatusManager

__all__ = [
    "ClientAuthService",
    "ClientRegistration",
    "IdentifiedClient",
]


@dataclass
class ClientRegistration:
    """Result of client registration."""

    client_id: str
    display_name: str


@dataclass
class IdentifiedClient:
    """Result of successful client identification."""

    client_id: str
    display_name: str
    client_type: str
    status: str
    rate_limit_rpm: int
    rate_limit_tpm: int


class ClientAuthService:
    """Service for client registration and management."""

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
        """Register a new client.

        Args:
            display_name: Human-readable name for the client
            client_type: One of "internal", "external", "service"
            rate_limit_rpm: Requests per minute limit
            rate_limit_tpm: Tokens per minute limit

        Returns:
            ClientRegistration with the client_id
        """
        client_id = str(uuid.uuid4())

        client = Client(
            id=client_id,
            display_name=display_name,
            client_type=client_type,
            status="active",
            rate_limit_rpm=rate_limit_rpm,
            rate_limit_tpm=rate_limit_tpm,
        )

        self.db.add(client)
        await self.db.commit()

        return ClientRegistration(
            client_id=client_id,
            display_name=display_name,
        )

    async def identify(self, client_id: str) -> IdentifiedClient | None:
        """Identify a client by ID.

        Args:
            client_id: The client UUID

        Returns:
            IdentifiedClient if found and active, None otherwise
        """
        result = await self.db.execute(select(Client).where(Client.id == client_id))
        client = result.scalar_one_or_none()

        if not client:
            return None

        if client.status != "active":
            return None

        # Update last_used_at
        await self.db.execute(
            update(Client).where(Client.id == client_id).values(last_used_at=datetime.now(UTC))
        )
        await self.db.commit()

        return IdentifiedClient(
            client_id=client.id,
            display_name=client.display_name,
            client_type=client.client_type,
            status=client.status,
            rate_limit_rpm=client.rate_limit_rpm,
            rate_limit_tpm=client.rate_limit_tpm,
        )

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
