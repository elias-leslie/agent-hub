"""Special handling for st-cli.md splitting into functional clusters.

Per decision d1: Split st-cli.md into functional clusters for better retrieval.
"""


def extract_st_cli_clusters(filename: str, content: str, meta: dict) -> list[dict]:
    """Extract st-cli.md into functional clusters per decision d1.

    Clusters:
    1. Active Workflow - ready, context, update, close, subtask, step
    2. Planning & Approval - approve, qa, import, verify
    3. Task Management - create, list, show, bug, claim, log
    4. Quality Gate - health, criterion
    5. System Commands - projects, backup, git, sessions, exec
    6. ID Formats & Anti-patterns - ID format rules, errors table
    """
    learnings = []

    # Define clusters with their sections
    clusters = {
        "active_workflow": {
            "title": "st CLI: Active Workflow Commands",
            "description": "Day-to-day task execution commands for SummitFlow CLI",
            "keywords": ["ready", "context", "update", "close", "subtask", "step", "claim", "log"],
            "category": "operational_context",
            "is_golden": True,
        },
        "planning_approval": {
            "title": "st CLI: Planning & Approval",
            "description": "Plan approval and QA workflow commands",
            "keywords": ["approve", "qa", "import", "verify", "Plan Approval"],
            "category": "operational_context",
            "is_golden": True,
        },
        "task_management": {
            "title": "st CLI: Task Management",
            "description": "Creating and managing tasks in SummitFlow",
            "keywords": ["create", "list", "show", "bug", "delete", "cancel"],
            "category": "operational_context",
            "is_golden": True,
        },
        "quality_gate": {
            "title": "st CLI: Quality Gate & Criteria",
            "description": "Health checks and acceptance criteria management",
            "keywords": ["health", "criterion", "Health", "HEALTH"],
            "category": "operational_context",
            "is_golden": True,
        },
        "system_commands": {
            "title": "st CLI: System Commands",
            "description": "Project management, backup, git, and session commands",
            "keywords": ["projects", "backup", "git", "sessions", "exec", "worktree", "autocode"],
            "category": "operational_context",
            "is_golden": False,
        },
    }

    # Extract ID formats and anti-patterns as separate TROUBLESHOOTING_GUIDE entries
    id_format_section = _extract_section(content, "plan.json Schema", "Anti-Patterns")
    if id_format_section:
        learnings.append(
            {
                "content": f"# st CLI: ID Formats (plan.json)\n\n{id_format_section}",
                "category": "troubleshooting_guide",
                "tier": "reference",
                "is_golden": True,
                "is_anti_pattern": False,
                "source_description": "troubleshooting_guide reference source:golden_standard confidence:100 cluster:st_cli_id_formats migrated_from:st-cli.md",
            }
        )

    anti_patterns_section = _extract_section(content, "Anti-Patterns", "Errors")
    if anti_patterns_section:
        learnings.append(
            {
                "content": f"# st CLI: Anti-Patterns\n\n{anti_patterns_section}",
                "category": "troubleshooting_guide",
                "tier": "reference",
                "is_golden": True,
                "is_anti_pattern": True,
                "source_description": "troubleshooting_guide reference source:golden_standard confidence:100 type:anti_pattern cluster:st_cli_anti_patterns migrated_from:st-cli.md",
            }
        )

    errors_section = _extract_section(content, "Errors", None)
    if errors_section:
        learnings.append(
            {
                "content": f"# st CLI: Common Errors\n\n{errors_section}",
                "category": "troubleshooting_guide",
                "tier": "reference",
                "is_golden": True,
                "is_anti_pattern": False,
                "source_description": "troubleshooting_guide reference source:golden_standard confidence:100 cluster:st_cli_errors migrated_from:st-cli.md",
            }
        )

    # Extract each cluster
    for cluster_id, cluster_meta in clusters.items():
        cluster_content = _extract_cluster_content(content, cluster_meta["keywords"])
        if cluster_content:
            source_desc = (
                f"{cluster_meta['category']} reference "
                f"source:{'golden_standard' if cluster_meta['is_golden'] else 'rule_migration'} "
                f"confidence:{'100' if cluster_meta['is_golden'] else '95'} "
                f"cluster:st_cli_{cluster_id} migrated_from:st-cli.md"
            )

            learnings.append(
                {
                    "content": f"# {cluster_meta['title']}\n\n{cluster_meta['description']}\n\n{cluster_content}",
                    "category": cluster_meta["category"],
                    "tier": "reference",
                    "is_golden": cluster_meta["is_golden"],
                    "is_anti_pattern": False,
                    "source_description": source_desc,
                }
            )

    return learnings


def _extract_section(content: str, start_header: str, end_header: str | None) -> str:
    """Extract content between two headers."""
    lines = content.split("\n")
    in_section = False
    section_lines = []

    for line in lines:
        if f"## {start_header}" in line or f"# {start_header}" in line:
            in_section = True
            section_lines.append(line)
            continue

        if in_section:
            if end_header and (f"## {end_header}" in line or f"# {end_header}" in line):
                break
            section_lines.append(line)

    return "\n".join(section_lines).strip()


def _extract_cluster_content(content: str, keywords: list[str]) -> str:
    """Extract lines containing any of the keywords."""
    lines = content.split("\n")
    relevant_lines = []
    in_code_block = False
    include_block = False

    for i, line in enumerate(lines):
        # Track code blocks
        if line.strip().startswith("```"):
            if in_code_block:
                if include_block:
                    relevant_lines.append(line)
                in_code_block = False
                include_block = False
            else:
                in_code_block = True
                # Check if code block content is relevant
                include_block = any(
                    kw.lower() in lines[i + 1].lower() if i + 1 < len(lines) else False
                    for kw in keywords
                )
                if include_block:
                    relevant_lines.append(line)
            continue

        if in_code_block:
            if include_block:
                relevant_lines.append(line)
            continue

        # Check for keyword matches
        if any(kw.lower() in line.lower() for kw in keywords):
            relevant_lines.append(line)
            # Include next few lines for context (tables, etc.)
            for j in range(1, 3):
                if i + j < len(lines) and lines[i + j].strip().startswith("|"):
                    relevant_lines.append(lines[i + j])

    return "\n".join(relevant_lines).strip()
