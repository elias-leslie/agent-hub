"""Agent Hub API path constants.

Single source of truth for every API path the CLI uses.
Parameterized paths use str.format() placeholders.
"""

from __future__ import annotations

# ── Memory ───────────────────────────────────────────────────────────
MEMORY_STATS_PATH = "/api/memory/stats"
MEMORY_LIST_PATH = "/api/memory/list"
MEMORY_SEARCH_PATH = "/api/memory/search"
MEMORY_SAVE_LEARNING_PATH = "/api/memory/save-learning"
MEMORY_BATCH_GET_PATH = "/api/memory/batch-get"
MEMORY_BATCH_UPDATE_PATH = "/api/memory/batch-update"
MEMORY_BULK_DELETE_PATH = "/api/memory/bulk-delete"
MEMORY_BULK_TAG_PATH = "/api/memory/episodes/bulk-tag"
MEMORY_CLEANUP_PATH = "/api/memory/cleanup"
MEMORY_TASK_OUTCOME_PATH = "/api/memory/task-outcome"
MEMORY_TRIGGERED_REFS_PATH = "/api/memory/triggered-references"
MEMORY_PHASE_TRIGGERED_REFS_PATH = "/api/memory/phase-triggered-references"
MEMORY_PROGRESSIVE_CONTEXT_PATH = "/api/memory/progressive-context"
MEMORY_SCOPE_PREVIEW_PATH = "/api/runtime-context/memory-scope/preview"
MEMORY_SCOPE_APPLY_PATH = "/api/runtime-context/memory-scope/apply"

# Parameterized (use .format())
MEMORY_EPISODE_PATH = "/api/memory/episode/{uuid}"
MEMORY_EPISODE_PROPERTIES_PATH = "/api/memory/episode/{uuid}/properties"
MEMORY_EPISODE_REVISIONS_PATH = "/api/memory/episode/{uuid}/revisions"
MEMORY_EPISODE_RESTORE_PATH = "/api/memory/episode/{uuid}/revisions/{revision_id}/restore"
MEMORY_EPISODE_TAGS_PATH = "/api/memory/episodes/{uuid}/tags"

# ── Agents ───────────────────────────────────────────────────────────
AGENTS_BASE_PATH = "/api/agents"
AGENTS_PREVIEW_PATH = "/api/agents/{slug}/preview"
MODELS_BASE_PATH = "/api/models"

# ── Prompts ──────────────────────────────────────────────────────────
PROMPTS_BASE_PATH = "/api/prompts"
PROMPT_REVISIONS_PATH = "/api/prompts/{slug}/revisions"
PROMPT_RESTORE_PATH = "/api/prompts/{slug}/revisions/{revision_id}/restore"

# ── Persona & Heartbeat ─────────────────────────────────────────────
PERSONA_BASE_PATH = "/api/persona"
HEARTBEAT_BASE_PATH = "/api/heartbeat"

# ── Complete ─────────────────────────────────────────────────────────

# ── Admin ────────────────────────────────────────────────────────────
ACCESS_CONTROL_METRICS_PATH = "/api/access-control/metrics"

# ── Automations ──────────────────────────────────────────────────────
AUTOMATIONS_BASE_PATH = "/api/automations"
AUTOMATIONS_REGISTRY_PATH = f"{AUTOMATIONS_BASE_PATH}/registry"
AUTOMATIONS_PROFILES_PATH = f"{AUTOMATIONS_BASE_PATH}/profiles"
AUTOMATIONS_RUNS_PATH = f"{AUTOMATIONS_BASE_PATH}/runs"
AUTOMATIONS_POLICY_PATH = f"{AUTOMATIONS_BASE_PATH}/projects/{{project_id}}/policy"
PROJECT_PERMISSION_PATH = "/api/projects/{project_id}/permissions"
