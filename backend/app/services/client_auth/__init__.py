"""Client registration and identification service.

Provides:
- Client registration with UUID generation
- Client status management (active, suspended, blocked)
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Client

from .status_manager import ClientStatusManager

__all__ = [
    "ClientAuthService",
    "ClientRegistration",
]


@dataclass
class ClientRegistration:
    """Result of client registration."""

    client_id: str
    display_name: str


class ClientAuthService:
    """Service for client registration and management."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self._status_manager = ClientStatusManager(db)

    async def register_client(
        self,
        display_name: str,
        client_type: str = "external",
    ) -> ClientRegistration:
        """Register a new client.

        Args:
            display_name: Human-readable name for the client
            client_type: One of "internal", "external", "service"

        Returns:
            ClientRegistration with the client_id
        """
        client_id = str(uuid.uuid4())

        client = Client(
            id=client_id,
            display_name=display_name,
            client_type=client_type,
            status="active",
        )

        self.db.add(client)
        await self.db.commit()

        return ClientRegistration(
            client_id=client_id,
            display_name=display_name,
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
