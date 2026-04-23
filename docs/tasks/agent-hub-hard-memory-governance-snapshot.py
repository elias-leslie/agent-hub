from __future__ import annotations

import asyncio
import json
from collections import defaultdict

from sqlalchemy import select

from app.constants.subtask_types import SUBTASK_TYPES
from app.db import async_session
from app.models import Memory
from app.services.memory.applicability import (
    applicability_has_exclusions,
    applicability_has_targets,
    normalize_applicability,
    normalize_context_kind,
    normalize_trigger_task_types,
)
from app.services.memory.repository import TIER_REVERSE

STARTUP_PROFILES = {"claude_session_start", "codex_startup"}
DELIVERY_ELIGIBLE_TIERS = {"mandate", "guardrail", "reference"}


def label_for(row, summary, content):
    return (row.name or summary or content or str(row.id))[:80]


async def main() -> None:
    async with async_session() as db:
        result = await db.execute(
            select(
                Memory.id,
                Memory.name,
                Memory.content,
                Memory.summary,
                Memory.context_kind,
                Memory.memory_type,
                Memory.tier,
                Memory.trigger_task_types,
                Memory.applicability,
                Memory.loaded_count,
            ).where(Memory.status == "active")
        )
        rows = result.all()

    hard_counts = {
        'policy_with_targeting_count': 0,
        'invalid_trigger_task_type_count': 0,
        'startup_profile_agent_target_count': 0,
    }
    working = defaultdict(lambda: {'issue_classes': [], 'label': '', 'loaded_count': 0, 'details': []})
    canonical_task_types = set(SUBTASK_TYPES)

    for row in rows:
        tier_name = TIER_REVERSE.get(int(row.tier or 0), 'reference')
        if tier_name not in DELIVERY_ELIGIBLE_TIERS:
            continue
        context_kind = normalize_context_kind(
            row.context_kind,
            memory_type=row.memory_type,
            tier=row.tier,
        ).value
        applicability = normalize_applicability(row.applicability)
        raw_trigger_types = row.trigger_task_types if isinstance(row.trigger_task_types, list) else []
        normalized_trigger_types = normalize_trigger_task_types(raw_trigger_types)
        summary = (row.summary or '').strip()
        content = (row.content or '').strip()
        uid = str(row.id)
        entry = working[uid]
        entry['label'] = label_for(row, summary, content)
        entry['loaded_count'] = int(row.loaded_count or 0)

        has_targets = applicability_has_targets(applicability)
        has_exclusions = applicability_has_exclusions(applicability)
        if context_kind == 'policy' and (has_targets or has_exclusions):
            hard_counts['policy_with_targeting_count'] += 1
            entry['issue_classes'].append('policy_with_targeting')
            entry['details'].append('policy has targeting or exclusions')

        invalid_trigger_types = [t for t in normalized_trigger_types if t not in canonical_task_types]
        if invalid_trigger_types:
            hard_counts['invalid_trigger_task_type_count'] += 1
            entry['issue_classes'].append('invalid_trigger_task_type')
            entry['details'].append('invalid trigger types: ' + ', '.join(invalid_trigger_types))

        if set(applicability.consumer_profiles).intersection(STARTUP_PROFILES) and applicability.agent_slugs:
            hard_counts['startup_profile_agent_target_count'] += 1
            entry['issue_classes'].append('startup_profile_agent_target')
            entry['details'].append('startup profile plus agent slug targeting creates dead route')

    working_set = []
    for uid, data in working.items():
        if not data['issue_classes']:
            continue
        working_set.append({
            'uuid': uid,
            'issue_classes': sorted(set(data['issue_classes'])),
            'label': data['label'],
            'loaded_count': data['loaded_count'],
            'details': sorted(set(data['details'])),
        })

    working_set.sort(key=lambda item: (-item['loaded_count'], item['uuid']))
    payload = {
        'helper_version': 1,
        'health_status': 'critical' if any(hard_counts.values()) else 'healthy',
        **hard_counts,
        'working_set': working_set,
    }
    print(json.dumps(payload, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
