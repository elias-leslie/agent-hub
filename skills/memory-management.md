---
tier: guardrail
summary: When to save/update/delete memory episodes
trigger_task_types: [feature, refactor, bug]
pinned: false
tags: [skill:memory-management, memory]
---

# Memory Management Guidelines

## When to Save (st memory save)
- Reusable pattern discovered during implementation
- Cross-session knowledge that would be lost
- Architectural decisions with rationale
- Troubleshooting steps for recurring issues
- Not work logs, task status, heartbeat journals, session summaries, or app-specific records that already live in a project database

## When to Update (st memory update)
- Existing episode has stale information
- Pattern evolved or improved
- Scope or trigger types need adjustment

## When to Delete (st memory delete)
- Episode superseded by a better one
- Information is now incorrect
- Pattern no longer applies to the codebase

## Injection Tiers
- **mandate**: Must-follow rules, always injected. Use sparingly.
- **guardrail**: Context-specific rules, injected when relevant.
- **reference**: Background knowledge, injected on search match.

## Decision Tree
- LEARNING (reusable, cross-session) -> st memory save
- OPERATIONAL LOG / APP DATA (heartbeat status, task attempts, per-document extracts, raw confirmations) -> store in session events, summaries, or project DB instead
- FIX NOW (blocks current task, <5min) -> just fix it
- TASK (out of scope, needs planning, >15min) -> create task
