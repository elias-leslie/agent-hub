import asyncio

from sqlalchemy import select

from app.db import async_session
from app.models import Client


async def main():
    async with async_session() as db:
        # Search for client by display name (assuming 'summitflow-backend' matches display_name or part of it)
        # or we can list all clients to find the right one.
        result = await db.execute(select(Client))
        clients = result.scalars().all()

        found = False
        for client in clients:
            if (
                client.display_name == "summitflow-backend"
                or "summitflow" in client.display_name.lower()
            ):
                print(f"Found Client: {client.display_name} (ID: {client.id})")
                print(f"  Allowed Projects: {client.allowed_projects}")
                found = True

        if not found:
            print("Client 'summitflow-backend' not found via fuzzy search.")


if __name__ == "__main__":
    asyncio.run(main())
