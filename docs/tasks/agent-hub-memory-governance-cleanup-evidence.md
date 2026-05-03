# Agent Hub Memory Governance Cleanup Evidence

Task: task-3868b905

## Snapshot before

- health_status: critical
- policy_with_targeting_count: 32
- invalid_trigger_task_type_count: 3
- startup_profile_agent_target_count: 0
- untargeted_reference_count: 67
- oversized_policy_count: 10
- issue_count: 112

Export before destructive edits: `docs/tasks/agent-hub-memory-governance-cleanup-export.json` via `st memory export $(cat /tmp/memgov-uuids.txt) --full`; exported 80 working-set UUIDs.
Additional export before clearing policy applicability: `/tmp/memgov-policy-targeting-postinvalid-export.json`; exported 32 policy-targeting UUIDs.

## UUID actions

### Invalid trigger task types
- e87253e8-8232-49f0-bfcf-705f782125bc: trigger-types command -> devops; `st memory update --change-reason task-3868b905...`
- f1e7cfee-18fb-4f68-8af6-3bb756d00538: trigger-types prompt -> config; `st memory update --change-reason task-3868b905...`
- b8fa1121-d9ac-497d-8b7b-ac7d02fa7b6b: trigger-types memory -> config; `st memory update --change-reason task-3868b905...`

### Policy with targeting
- e40037f0-cbb4-45ed-8ed2-39303ba87726: cleared applicability targeting/exclusions; summary='Wait on quiet active sessions'
- 9200c6d5-b9aa-4fbf-87d2-d99c0990a59d: cleared applicability targeting/exclusions; summary='Use st vcs for git state'
- c4f0b1a1-e28f-419e-b846-8cdc291b021b: cleared applicability targeting/exclusions; summary='Reusable prompts live in DB'
- d301ef61-193f-4baa-8314-16dc28493d6d: cleared applicability targeting/exclusions; summary='No stubs or partials'
- bdee1bd4-2f84-4d0c-b26c-5400d17fcdf7: cleared applicability targeting/exclusions; summary='Prompt preview first'
- 4b318ac9-976e-4ffb-9b94-a695b1094277: cleared applicability targeting/exclusions; summary='Avoid destructive git'
- 23e0a93c-1375-4fc5-80ca-d0b7956bcdf1: cleared applicability targeting/exclusions; summary='Verify memory writes on error'
- 29888052-8b5e-4f11-a8c5-ccaf8e77008b: cleared applicability targeting/exclusions; summary='Measure Jenny by Jenny work'
- d7c57c77-ab4c-4bea-8cdc-5f867cb8d992: cleared applicability targeting/exclusions; summary='Use live plan schema'
- 62cc6631-c72d-44ed-9596-dcce42b993a6: cleared applicability targeting/exclusions; summary='project scope for project memories'
- 65fecbaf-9fc3-4404-8614-c48577a6becf: cleared applicability targeting/exclusions; summary='AH async-only'
- 8e9d0132-16e7-43a2-9fcf-639e1306e33a: cleared applicability targeting/exclusions; summary='Jenny autonomy boundary'
- 294b72c0-5206-42d4-af44-9f0047f96dd6: cleared applicability targeting/exclusions; summary='Jenny coach monitors friction'
- 689dac79-bb22-4419-afa7-f953d3c99b23: cleared applicability targeting/exclusions; summary='Keep st search first'
- 7126dedf-021d-4483-b99f-d4baa0149dd8: cleared applicability targeting/exclusions; summary='Claude OAuth not API keys'
- cf55594f-a375-45d1-9ba8-ef5b272276ab: cleared applicability targeting/exclusions; summary='Agent Hub Python SDK'
- 671c226d-b6d6-49f5-8438-8895d2f0f04f: cleared applicability targeting/exclusions; summary='No Jenny canary gating'
- 559a7509-5e85-4d89-95b6-068c212f5267: cleared applicability targeting/exclusions; summary='agent-hub frontend auth env'
- 341cc358-75cb-488d-bda6-4bf0f1fefd7a: cleared applicability targeting/exclusions; summary='Btrfs autosnapshot lifecycle rules'
- 919bbd8b-2e43-4d62-b827-a50ddbf63a77: cleared applicability targeting/exclusions; summary='st complete model override'
- 8d0bcbfd-34b0-4320-b256-0725e43fb725: cleared applicability targeting/exclusions; summary='Heartbeat uses CANCEL_NEWEST'
- 86a18930-9cd6-4d68-9e35-afe3c9ed561b: cleared applicability targeting/exclusions; summary='No arbitrary Jenny task caps'
- f1e7cfee-18fb-4f68-8af6-3bb756d00538: cleared applicability targeting/exclusions; summary='Prompt structure and measurement'
- b8fa1121-d9ac-497d-8b7b-ac7d02fa7b6b: cleared applicability targeting/exclusions; summary='Use standard memory format'
- 7eda96be-e401-4bd1-acfc-ce85c6759ee6: cleared applicability targeting/exclusions; summary='Snapshot recovery preference'
- bf6b7613-1333-46e9-922e-c55c5c8b24ea: cleared applicability targeting/exclusions; summary='Track selected vs index refs'
- a031902b-6e49-49e5-857c-7db10e3c2643: cleared applicability targeting/exclusions; summary='Use remote workflow truth'
- 505fb5fd-04c9-4940-a1d9-49b8819583db: cleared applicability targeting/exclusions; summary='Use st cleanroom'
- 44d99c69-e119-4633-9561-45ec2b364ebc: cleared applicability targeting/exclusions; summary='Use st vcs and commit'
- b8cc14fa-d179-46b7-b32f-655a60926618: cleared applicability targeting/exclusions; summary='Own VCS cleanup debt'
- c1252b83-37a3-4ec9-8544-ceb6ae7b367f: cleared applicability targeting/exclusions; summary='Preview matches runtime prompt'
- e5bf4460-2027-4791-9b9a-e2a91a298e38: cleared applicability targeting/exclusions; summary='Seed script stays insert-only'

### Untargeted references retargeted
- 1b4085fb-9336-4d8c-b925-78281171bae1: added consumer-profile or audience-tag targeting; reason `task-3868b905: retarget high-load untargeted reference for consumer-fit governance`
- d12c03bf-e1c6-4738-a579-c2eeffb36748: added consumer-profile or audience-tag targeting; reason `task-3868b905: retarget high-load untargeted reference for consumer-fit governance`
- a2d7da9c-53db-4eda-a10d-5f98de548004: added consumer-profile or audience-tag targeting; reason `task-3868b905: retarget high-load untargeted reference for consumer-fit governance`
- 78ddb3d9-d85d-44c0-82c5-f26c93a4b177: added consumer-profile or audience-tag targeting; reason `task-3868b905: retarget high-load untargeted reference for consumer-fit governance`
- 71463cc9-851b-4d85-b8fa-1a74eb1dbf93: added consumer-profile or audience-tag targeting; reason `task-3868b905: retarget high-load untargeted reference for consumer-fit governance`
- 8e6521e7-2027-4943-a30c-651cce33eb99: added consumer-profile or audience-tag targeting; reason `task-3868b905: retarget high-load untargeted reference for consumer-fit governance`
- 5f759e78-f8fe-4e66-8419-488b243c7401: added consumer-profile or audience-tag targeting; reason `task-3868b905: retarget high-load untargeted reference for consumer-fit governance`
- 6f2161f6-523f-4702-b396-bc0181833a25: added consumer-profile or audience-tag targeting; reason `task-3868b905: retarget high-load untargeted reference for consumer-fit governance`
- 691b0d9a-f130-4d61-9bb4-01ea3d5a5e22: added consumer-profile or audience-tag targeting; reason `task-3868b905: retarget high-load untargeted reference for consumer-fit governance`
- 1309caee-bd27-413a-81ba-1bff1c9d0083: added consumer-profile or audience-tag targeting; reason `task-3868b905: retarget high-load untargeted reference for consumer-fit governance`
- 740bd1ea-37f8-4251-9a97-4dcbff004824: added consumer-profile or audience-tag targeting; reason `task-3868b905: retarget high-load untargeted reference for consumer-fit governance`
- 05cc0918-0b93-4633-8fe2-ca79d01028ef: added consumer-profile or audience-tag targeting; reason `task-3868b905: retarget high-load untargeted reference for consumer-fit governance`
- b0de72c8-8720-452b-9a42-21e2424e4add: added consumer-profile or audience-tag targeting; reason `task-3868b905: retarget high-load untargeted reference for consumer-fit governance`
- 24f8d896-e523-4122-b32e-c917a2e17686: added consumer-profile or audience-tag targeting; reason `task-3868b905: retarget high-load untargeted reference for consumer-fit governance`
- 52c6a99e-e650-4825-a824-773c1da8e0c0: added consumer-profile or audience-tag targeting; reason `task-3868b905: retarget high-load untargeted reference for consumer-fit governance`
- e9b9df52-7994-4ee4-83b5-bf58b2a60ef4: added consumer-profile or audience-tag targeting; reason `task-3868b905: retarget high-load untargeted reference for consumer-fit governance`
- 99d7534a-deaf-4f19-85f2-4184fee433f8: added consumer-profile or audience-tag targeting; reason `task-3868b905: retarget high-load untargeted reference for consumer-fit governance`
- de45ef73-3720-4876-a276-a18617f09dc5: added consumer-profile or audience-tag targeting; reason `task-3868b905: retarget high-load untargeted reference for consumer-fit governance`
- 10461f67-7916-4140-8eb8-13dba34f8454: added consumer-profile or audience-tag targeting; reason `task-3868b905: retarget high-load untargeted reference for consumer-fit governance`
- 9fd4a296-4a72-4f7c-a9e4-77b8f01fde0c: added consumer-profile or audience-tag targeting; reason `task-3868b905: retarget high-load untargeted reference for consumer-fit governance`
- ccecd3f3-8e8f-4415-bdc0-0b0b9afd9720: added consumer-profile or audience-tag targeting; reason `task-3868b905: retarget high-load untargeted reference for consumer-fit governance`
- 8070b650-c3dd-4e95-b452-c3933fbb372a: added consumer-profile or audience-tag targeting; reason `task-3868b905: retarget high-load untargeted reference for consumer-fit governance`
- 71c9cfec-a48a-4ea5-ae1e-7556b9d67846: added consumer-profile or audience-tag targeting; reason `task-3868b905: retarget high-load untargeted reference for consumer-fit governance`
- 90210463-762b-4502-a3db-eae5368d010b: added consumer-profile or audience-tag targeting; reason `task-3868b905: retarget high-load untargeted reference for consumer-fit governance`
- 23cd85c9-ddca-433c-aece-34ae3978de83: added consumer-profile or audience-tag targeting; reason `task-3868b905: retarget high-load untargeted reference for consumer-fit governance`
- de7224f7-9321-4c02-aab9-38d4b6607df4: added consumer-profile or audience-tag targeting; reason `task-3868b905: retarget high-load untargeted reference for consumer-fit governance`
- c06f9644-1a5a-488d-844a-f424ba0dc658: added consumer-profile or audience-tag targeting; reason `task-3868b905: retarget high-load untargeted reference for consumer-fit governance`

Deletes: none.
Backend architecture changes: none.

## Snapshot after

- health_status: healthy
- policy_with_targeting_count: 0
- invalid_trigger_task_type_count: 0
- startup_profile_agent_target_count: 0
- untargeted_reference_count: 40
- oversized_policy_count: 10
- issue_count: 50

## Consumer-fit checks

- `st memory status --consumer-profile claude_session_start`: memory=OK attempts=1 latency_ms=601.
- `st memory status --consumer-profile codex_startup`: memory=OK attempts=1 latency_ms=74.
- Search spot check `credentials port docker compose shared checkout prompt preview finance` returned surviving retargeted references: 1b4085fb credentials, e9b9df52 ports, a2d7da9c Docker compose, 71463cc9 shared checkout, c06f9644 compose health, d12c03bf port map, de7224f7 pulse Docker path.

## Blockers

- none
