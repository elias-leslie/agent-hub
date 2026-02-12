"""Client status management operations."""

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Client


class ClientStatusManager:
    """Manages client status transitions (active, suspended, blocked)."""

    def __init__(self, db: AsyncSession):
        self.db = db

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
