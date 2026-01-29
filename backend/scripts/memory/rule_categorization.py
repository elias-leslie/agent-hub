"""Rule categorization metadata for migration to Graphiti.

Per decision d3: Graphiti-first with rules as read-only archive.
Rules are migrated with status='canonical' since they are vetted.
"""

# Explicit rule categorization from rules-categorization.md
# Maps filename (without .md) to (category, injection_tier, task_filters)
# injection_tier: MANDATE (always), GUARDRAIL (type-filtered), REFERENCE (semantic)
RULE_CATEGORIZATION: dict[str, dict] = {
    # MANDATE tier - always inject
    "anti-patterns": {
        "category": "troubleshooting_guide",
        "tier": "mandate",
        "is_anti_pattern": True,
        "is_golden": True,
    },
    "dev-tools-exclusive": {
        "category": "coding_standard",
        "tier": "mandate",
        "is_golden": True,
    },
    "session-protocol": {
        "category": "operational_context",
        "tier": "mandate",
        "is_golden": True,
    },
    "scope-awareness": {
        "category": "troubleshooting_guide",
        "tier": "mandate",
        "is_anti_pattern": True,
        "is_golden": True,
    },
    "interaction-style": {
        "category": "coding_standard",
        "tier": "mandate",
        "is_golden": True,
    },
    # GUARDRAIL tier - type-filtered
    "db-architecture": {
        "category": "system_design",
        "tier": "guardrail",
        "task_filters": ["database", "migration", "schema"],
        "is_golden": True,
    },
    "browser-testing": {
        "category": "coding_standard",
        "tier": "guardrail",
        "task_filters": ["testing", "ui", "frontend", "browser"],
        "is_golden": True,
    },
    "browser-server": {
        "category": "operational_context",
        "tier": "guardrail",
        "task_filters": ["browser", "playwright", "ba"],
    },
    "verification": {
        "category": "coding_standard",
        "tier": "guardrail",
        "task_filters": ["testing", "commit", "done"],
        "is_golden": True,
    },
    "quality-gate": {
        "category": "operational_context",
        "tier": "guardrail",
        "task_filters": ["commit", "testing", "quality"],
    },
    "cloudflare-access": {
        "category": "operational_context",
        "tier": "guardrail",
        "task_filters": ["deploy", "production", "api", "cloudflare"],
    },
    "voice-system": {
        "category": "system_design",
        "tier": "guardrail",
        "task_filters": ["voice", "audio", "whisper"],
    },
    "tech-debt-cleanup": {
        "category": "troubleshooting_guide",
        "tier": "guardrail",
        "task_filters": ["migration", "refactor", "cleanup"],
        "is_anti_pattern": True,
    },
    # REFERENCE tier - semantic retrieval
    "st-cli": {
        "category": "operational_context",
        "tier": "reference",
        "cluster": "cli_tools",
        "is_golden": True,
    },
    "dev-standards": {
        "category": "coding_standard",
        "tier": "reference",
        "cluster": "development_workflow",
        "is_golden": True,
    },
    "output-format-standard": {
        "category": "coding_standard",
        "tier": "reference",
        "cluster": "output_formatting",
    },
    "model-standards": {
        "category": "coding_standard",
        "tier": "reference",
        "cluster": "ai_llm_config",
        "is_golden": True,
    },
    "decision-making": {
        "category": "troubleshooting_guide",
        "tier": "reference",
        "cluster": "decision_process",
    },
    "skill-triggers": {
        "category": "operational_context",
        "tier": "reference",
        "cluster": "skill_system",
    },
    "rule-authoring": {
        "category": "coding_standard",
        "tier": "reference",
        "cluster": "meta_rules",
    },
    "api-config-pattern": {
        "category": "coding_standard",
        "tier": "reference",
        "cluster": "frontend_patterns",
    },
}


def get_rule_metadata(filename: str) -> dict:
    """Get explicit metadata for a rule file.

    Args:
        filename: Rule filename with .md extension

    Returns:
        Dict with category, tier, is_golden, is_anti_pattern, task_filters, cluster
    """
    from pathlib import Path

    stem = Path(filename).stem

    # Use explicit mapping if available
    if stem in RULE_CATEGORIZATION:
        meta = RULE_CATEGORIZATION[stem].copy()
        # Set defaults
        meta.setdefault("is_golden", False)
        meta.setdefault("is_anti_pattern", False)
        meta.setdefault("task_filters", [])
        meta.setdefault("cluster", None)
        return meta

    # Fallback to pattern inference for unknown files
    return {
        "category": _infer_category_fallback(filename),
        "tier": "reference",
        "is_golden": False,
        "is_anti_pattern": False,
        "task_filters": [],
        "cluster": None,
    }


def _infer_category_fallback(filename: str) -> str:
    """Fallback category inference for unmapped files."""
    filename_lower = filename.lower()

    if any(kw in filename_lower for kw in ["anti", "gotcha", "pitfall", "error"]):
        return "troubleshooting_guide"
    if any(kw in filename_lower for kw in ["standard", "style", "pattern"]):
        return "coding_standard"
    if any(kw in filename_lower for kw in ["architecture", "design", "system"]):
        return "system_design"
    if any(kw in filename_lower for kw in ["deploy", "server", "config", "protocol"]):
        return "operational_context"

    return "domain_knowledge"
