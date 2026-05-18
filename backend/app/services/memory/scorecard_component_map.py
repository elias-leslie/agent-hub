"""Component ID registry for the agent feedback scorecard system.

Maps tool names, event types, and error patterns to component IDs.
Component IDs use dot notation: project.subsystem (e.g. sf.cli, ah.memory).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ComponentInfo:
    """Metadata about a scoreable component."""

    id: str
    name: str
    project: str  # summitflow, agent-hub, cross-cutting
    description: str


# --- Component Registry ---

COMPONENTS: dict[str, ComponentInfo] = {
    # SummitFlow components
    "sf.cli": ComponentInfo(
        id="sf.cli",
        name="ST CLI",
        project="summitflow",
        description="Task CRUD, claim/done/abandon, context, checkpoints",
    ),
    "sf.cli.memory": ComponentInfo(
        id="sf.cli.memory",
        name="ST Memory CLI",
        project="summitflow",
        description="Memory search, save, batch-import, seed",
    ),
    "sf.dt": ComponentInfo(
        id="sf.dt",
        name="Dev Tools (dt)",
        project="summitflow",
        description="pytest, ruff, types, biome, tsc, sqlfluff quality wrappers",
    ),
    "sf.quality": ComponentInfo(
        id="sf.quality",
        name="Quality Gates",
        project="summitflow",
        description="run_execution_quality_check, intent checks, auto-pass steps",
    ),
    "sf.checkpoints": ComponentInfo(
        id="sf.checkpoints",
        name="Checkpoints",
        project="summitflow",
        description="Checkpoint creation, cleanup, and task-branch management",
    ),
    "sf.api": ComponentInfo(
        id="sf.api",
        name="SummitFlow API",
        project="summitflow",
        description="Tasks, projects, explorer, quality, events endpoints",
    ),
    "sf.storage": ComponentInfo(
        id="sf.storage",
        name="Storage Layer",
        project="summitflow",
        description="Raw SQL queries, connection pool, CRUD modules",
    ),
    "sf.workflows": ComponentInfo(
        id="sf.workflows",
        name="Hatchet Workflows",
        project="summitflow",
        description="Pipeline stages: ideate, triage, plan, execute, review",
    ),
    "sf.explorer": ComponentInfo(
        id="sf.explorer",
        name="Code Explorer",
        project="summitflow",
        description="Analyzers, health scoring, scan history",
    ),
    "sf.frontend": ComponentInfo(
        id="sf.frontend",
        name="Frontend UI",
        project="summitflow",
        description="Task views, explorer, kanban, health panels",
    ),
    "sf.search": ComponentInfo(
        id="sf.search",
        name="Precision Code Search",
        project="summitflow",
        description="st search, symbol/text/endpoint search, explorer index",
    ),
    "sf.scripts": ComponentInfo(
        id="sf.scripts",
        name="Infrastructure Scripts",
        project="summitflow",
        description="restart.sh, rebuild.sh, backup.sh, commit.sh",
    ),
    "sf.graph": ComponentInfo(
        id="sf.graph",
        name="Code Graph (graphify)",
        project="summitflow",
        description="st graph context/query/path/explain; community hubs, semantic coverage",
    ),
    "sf.wiki": ComponentInfo(
        id="sf.wiki",
        name="Project Wiki",
        project="summitflow",
        description="st wiki query and stored knowledge surface",
    ),
    "sf.browser": ComponentInfo(
        id="sf.browser",
        name="Browser VM",
        project="summitflow",
        description="st browser check, screenshots, DOM snapshots, approved-VM routing",
    ),
    "sf.snapshots": ComponentInfo(
        id="sf.snapshots",
        name="Local Snapshots",
        project="summitflow",
        description="st snap/snaps/recover/rollback; Btrfs-backed project scope state",
    ),
    "sf.feedback": ComponentInfo(
        id="sf.feedback",
        name="Feedback System",
        project="summitflow",
        description="st feedback CLI/API, component registry, scorecards",
    ),
    # Agent Hub components
    "ah.memory": ComponentInfo(
        id="ah.memory",
        name="Memory System",
        project="agent-hub",
        description="Context injection, progressive context, budget management",
    ),
    "ah.memory.tiers": ComponentInfo(
        id="ah.memory.tiers",
        name="Memory Tiers",
        project="agent-hub",
        description="Mandates, guardrails, references, adaptive index",
    ),
    "ah.memory.continuity": ComponentInfo(
        id="ah.memory.continuity",
        name="Session Continuity",
        project="agent-hub",
        description="Recent activity, cross-project, live sessions",
    ),
    "ah.memory.citations": ComponentInfo(
        id="ah.memory.citations",
        name="Citation Tracking",
        project="agent-hub",
        description="[M:uuid], [G:uuid], [R:uuid] scanning and credit",
    ),
    "ah.memory.learning": ComponentInfo(
        id="ah.memory.learning",
        name="Learning Extraction",
        project="agent-hub",
        description="learning_extractor, confidence scoring",
    ),
    "ah.completion": ComponentInfo(
        id="ah.completion",
        name="Completion API",
        project="agent-hub",
        description="Agent routing, fallback chains, streaming",
    ),
    "ah.adapters": ComponentInfo(
        id="ah.adapters",
        name="Model Adapters",
        project="agent-hub",
        description="Claude, Gemini, OpenAI, tool calling",
    ),
    "ah.sessions": ComponentInfo(
        id="ah.sessions",
        name="Session Management",
        project="agent-hub",
        description="Create, events, close, branching, summaries",
    ),
    "ah.sdk": ComponentInfo(
        id="ah.sdk",
        name="Python SDK",
        project="agent-hub",
        description="Sync/async client, completion, memory, streaming",
    ),
    "ah.orchestration": ComponentInfo(
        id="ah.orchestration",
        name="Agent Orchestration",
        project="agent-hub",
        description="Subagent, parallel, maker-checker",
    ),
    "ah.hooks": ComponentInfo(
        id="ah.hooks",
        name="Claude Code Hooks",
        project="agent-hub",
        description="SessionStart, PreToolUse, PostToolUse, Stop",
    ),
    # Cross-cutting components
    "xc.tool_registry": ComponentInfo(
        id="xc.tool_registry",
        name="Tool Registry",
        project="cross-cutting",
        description="tool-registry.json and its 3 consumers",
    ),
    "xc.error_handling": ComponentInfo(
        id="xc.error_handling",
        name="Error Messages",
        project="cross-cutting",
        description="API errors, CLI errors, hook errors",
    ),
    "xc.documentation": ComponentInfo(
        id="xc.documentation",
        name="Documentation",
        project="cross-cutting",
        description="Memory context, CLAUDE.md, .index.yaml",
    ),
    "xc.testing": ComponentInfo(
        id="xc.testing",
        name="Test Infrastructure",
        project="cross-cutting",
        description="conftest, dt integration, test isolation",
    ),
}

# --- Tool Name → Component ID Mapping ---
# Used by PostToolUse.sh friction auto-detection and scorecard generator

TOOL_TO_COMPONENT: dict[str, str] = {
    # dt-wrapped tools
    "pytest": "sf.dt",
    "ruff": "sf.dt",
    "types": "sf.dt",
    "mypy": "sf.dt",
    "ty": "sf.dt",
    "biome": "sf.dt",
    "tsc": "sf.dt",
    "sqlfluff": "sf.dt",
    "squawk": "sf.dt",
    "dt": "sf.dt",
    # st CLI commands
    "st": "sf.cli",
    "st claim": "sf.cli",
    "st done": "sf.cli",
    "st context": "sf.cli",
    "st abandon": "sf.cli",
    "st pulse": "sf.cli",
    "st commit": "sf.cli",
    "st jj": "sf.cli",
    "st vcs": "sf.cli",
    "st check": "sf.dt",
    "st autocode": "sf.workflows",
    "st memory": "sf.cli.memory",
    "st search": "sf.search",
    "st graph": "sf.graph",
    "st wiki": "sf.wiki",
    "st browser": "sf.browser",
    "st snap": "sf.snapshots",
    "st snaps": "sf.snapshots",
    "st recover": "sf.snapshots",
    "st rollback": "sf.snapshots",
    "st feedback": "sf.feedback",
    "st complete": "ah.completion",
    "st agent": "ah.completion",
    # Infrastructure
    "restart.sh": "sf.scripts",
    "rebuild.sh": "sf.scripts",
    "backup.sh": "sf.scripts",
    "commit.sh": "sf.scripts",
    "db": "sf.storage",
    # CC tools
    "Write": "ah.hooks",
    "Edit": "ah.hooks",
    "Bash": "ah.hooks",
    "Read": "ah.hooks",
    "Glob": "ah.hooks",
    "Grep": "ah.hooks",
}

# --- Event Type → Component ID Mapping ---
# Used by scorecard generator to identify which components a session interacted with

EVENT_TYPE_TO_COMPONENT: dict[str, str] = {
    "memory_inject": "ah.memory",
    "memory_cite": "ah.memory.citations",
}


def get_component(component_id: str) -> ComponentInfo | None:
    """Look up component info by ID."""
    return COMPONENTS.get(component_id)


def resolve_component_from_tool(tool_name: str) -> str | None:
    """Resolve a tool name to its component ID.

    Tries exact match first, then prefix match for compound commands.
    """
    if tool_name in TOOL_TO_COMPONENT:
        return TOOL_TO_COMPONENT[tool_name]

    # Try prefix match (e.g., "st memory search" → "st memory" → "sf.cli.memory")
    parts = tool_name.split()
    while len(parts) > 1:
        parts.pop()
        prefix = " ".join(parts)
        if prefix in TOOL_TO_COMPONENT:
            return TOOL_TO_COMPONENT[prefix]

    return None


def get_all_component_ids() -> list[str]:
    """Return all registered component IDs."""
    return sorted(COMPONENTS.keys())


def get_components_by_project(project: str) -> list[ComponentInfo]:
    """Return components for a specific project."""
    return [c for c in COMPONENTS.values() if c.project == project]


def is_valid_component_id(component_id: str) -> bool:
    """Check if a component ID is registered."""
    return component_id in COMPONENTS
