#!/usr/bin/env python3
"""
One-time migration to fix episode timestamps in Neo4j.

Problem: Episodes were stored with naive timestamps (localdatetime) which breaks
Graphiti's retrieve_episodes() query that uses timezone-aware datetime comparisons.

Solution: Convert all localdatetime values to datetime with UTC timezone.

Usage:
    python backend/scripts/fix_episode_timestamps.py
"""

import asyncio
import os
import sys

# Add backend to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv(os.path.expanduser("~/.env.local"))


async def main():
    from app.services.memory.graphiti_client import get_graphiti

    graphiti = get_graphiti()
    driver = graphiti.driver

    print("Checking for episodes with localdatetime timestamps...")

    # First, count episodes by timestamp type
    count_query = """
    MATCH (e:Episodic)
    WITH e,
         CASE
           WHEN toString(e.valid_at) ENDS WITH 'Z' OR toString(e.valid_at) CONTAINS '+' THEN 'datetime'
           ELSE 'localdatetime'
         END AS ts_type
    RETURN ts_type, COUNT(*) AS count
    """

    records, _, _ = await driver.execute_query(count_query)
    for r in records:
        print(f"  {r['ts_type']}: {r['count']} episodes")

    # Ask for confirmation
    print("\nThis will convert all localdatetime timestamps to UTC datetime.")
    response = input("Proceed? (yes/no): ")
    if response.lower() != "yes":
        print("Aborted.")
        return

    # Fix the timestamps by converting localdatetime to datetime with UTC
    # The localdatetime values were stored assuming they were in the server's local timezone
    # We'll convert them to UTC datetime
    fix_query = """
    MATCH (e:Episodic)
    WHERE NOT (toString(e.valid_at) ENDS WITH 'Z' OR toString(e.valid_at) CONTAINS '+')
    WITH e, e.valid_at AS old_valid_at, e.created_at AS old_created_at
    SET e.valid_at = datetime({
        year: old_valid_at.year,
        month: old_valid_at.month,
        day: old_valid_at.day,
        hour: old_valid_at.hour,
        minute: old_valid_at.minute,
        second: old_valid_at.second,
        nanosecond: old_valid_at.nanosecond,
        timezone: 'UTC'
    })
    SET e.created_at = datetime({
        year: old_created_at.year,
        month: old_created_at.month,
        day: old_created_at.day,
        hour: old_created_at.hour,
        minute: old_created_at.minute,
        second: old_created_at.second,
        nanosecond: old_created_at.nanosecond,
        timezone: 'UTC'
    })
    RETURN COUNT(*) AS fixed_count
    """

    print("\nFixing timestamps...")
    records, _, _ = await driver.execute_query(fix_query)
    fixed_count = records[0]["fixed_count"] if records else 0
    print(f"Fixed {fixed_count} episodes.")

    # Verify
    print("\nVerifying...")
    records, _, _ = await driver.execute_query(count_query)
    for r in records:
        print(f"  {r['ts_type']}: {r['count']} episodes")

    print("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
