import asyncio
import json

from sqlalchemy import select

from app.db import async_session
from app.models import Client


async def main():
    async with async_session() as db:
        # Find client
        result = await db.execute(select(Client))
        clients = result.scalars().all()

        target_client = None
        for client in clients:
            if client.display_name == "summitflow-backend":
                target_client = client
                break

        if not target_client:
            print("Client 'summitflow-backend' not found.")
            return

        print(f"Updating permissions for: {target_client.display_name}")

        current_projects = []
        if target_client.allowed_projects:
            try:
                current_projects = json.loads(target_client.allowed_projects)
            except:
                pass

        print(f"Current projects: {current_projects}")

        if "monkey-fight" not in current_projects:
            current_projects.append("monkey-fight")
            target_client.allowed_projects = json.dumps(current_projects)
            await db.commit()
            print(f"Updated projects: {current_projects}")
        else:
            print("Project 'monkey-fight' already allowed.")


if __name__ == "__main__":
    asyncio.run(main())
