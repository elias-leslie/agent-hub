"""Report formatting and display for episode audits."""

from typing import Any


def print_audit_summary(audit_report: dict[str, Any], verbose: bool = False) -> None:
    """
    Display audit report summary to console.

    Args:
        audit_report: Audit results from analyze_episodes
        verbose: Include verbose pattern details
    """
    print("\n" + "=" * 60)
    print("EPISODE AUDIT REPORT")
    print("=" * 60)
    print(f"Total Episodes: {audit_report['total_episodes']}")
    print(f"Total Groups: {audit_report['total_groups']}")
    print(f"Legacy Groups: {audit_report['legacy_groups_count']}")
    print(f"Verbose Patterns Detected: {audit_report['verbose_pattern_count']}")

    print_group_distribution(audit_report)
    print_legacy_groups(audit_report)

    if verbose and audit_report.get("verbose_patterns"):
        print_verbose_patterns(audit_report)

    print("\n" + "=" * 60)


def print_group_distribution(audit_report: dict[str, Any]) -> None:
    """Print group distribution statistics."""
    print("\nGroup Distribution:")
    sorted_groups = sorted(
        audit_report["group_distribution"].items(),
        key=lambda x: x[1],
        reverse=True,
    )
    for group_id, count in sorted_groups:
        entity_count = audit_report["entity_distribution"].get(group_id, 0)
        legacy_marker = " [LEGACY]" if group_id in audit_report["legacy_groups"] else ""
        print(f"  {group_id}: {count} episodes, {entity_count} entities{legacy_marker}")


def print_legacy_groups(audit_report: dict[str, Any]) -> None:
    """Print legacy group details."""
    if not audit_report["legacy_groups"]:
        return

    print("\nLegacy Groups Details:")
    for group_id, stats in audit_report["legacy_groups"].items():
        print(f"  {group_id}: {stats['count']} episodes, {stats['entity_count']} entities")


def print_verbose_patterns(audit_report: dict[str, Any]) -> None:
    """Print verbose pattern details (first 10)."""
    patterns = audit_report["verbose_patterns"]
    print(f"\nVerbose Patterns Found ({len(patterns)}):")
    for pattern in patterns[:10]:
        print(f"\n  UUID: {pattern['uuid']}")
        print(f"  Group: {pattern['group_id']}")
        print(f"  Created: {pattern['created_at']}")
        print(f"  Preview: {pattern['content_preview']}")
