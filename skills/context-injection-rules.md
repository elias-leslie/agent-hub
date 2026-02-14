---
tier: reference
summary: Context injection tier selection criteria
trigger_task_types: [feature, refactor]
pinned: false
tags: [skill:context-injection-rules, memory, injection]
---

# Context Injection Rules

## Tier Selection Criteria

### Mandate (always injected)
- Security constraints (credential handling, access control)
- Critical workflow rules (commit via /commit_it, never direct git)
- Invariants that must never be violated
- Maximum: ~10 mandates per project to avoid context bloat

### Guardrail (injected when task type matches)
- Development standards (TDD, type safety, DRY)
- Tool usage rules (dt, db, restart.sh)
- Decision frameworks (1-3-1 gate, decision tree)
- Per-task-type rules (autocode-specific, review-specific)

### Reference (injected on semantic search match)
- Architecture documentation (service maps, port assignments)
- CLI usage guides (st, dt, db command references)
- Troubleshooting playbooks
- Historical decisions and their rationale

## Trigger Task Types
- Use `trigger_task_types` to scope guardrails to relevant tasks
- Common types: review, refactor, bug, feature, chore, docs
- Empty trigger types = inject for all task types

## Pinned Episodes
- Pin episodes that should always appear in reference index
- Maximum ~20 pinned references to avoid index bloat
- Review pinned episodes monthly for relevance
