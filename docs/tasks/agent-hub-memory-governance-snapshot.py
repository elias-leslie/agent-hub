from __future__ import annotations

import asyncio
import json

from app.db import async_session
from app.services.memory.governance import collect_memory_governance_snapshot


async def main() -> None:
    async with async_session() as db:
        snap = await collect_memory_governance_snapshot(db, sample_limit=10)
    keep = {
        'health_status': snap['health_status'],
        'untargeted_reference_count': snap['untargeted_reference_count'],
        'policy_with_targeting_count': snap['policy_with_targeting_count'],
        'invalid_trigger_task_type_count': snap['invalid_trigger_task_type_count'],
        'startup_profile_agent_target_count': snap['startup_profile_agent_target_count'],
        'oversized_policy_count': snap['oversized_policy_count'],
        'issue_count': snap['issue_count'],
        'untargeted_reference_samples': snap['untargeted_reference_samples'],
        'oversized_policy_samples': snap['oversized_policy_samples'],
        'startup_profile_agent_target_samples': snap['startup_profile_agent_target_samples'],
        'invalid_trigger_task_type_samples': snap['invalid_trigger_task_type_samples'],
    }
    print(json.dumps(keep, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
