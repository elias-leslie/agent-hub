"""UI formatting and display functions for legacy cleanup."""


def format_created_at(created_at) -> str:
    """Format created_at timestamp for display."""
    if hasattr(created_at, "to_native"):
        return created_at.to_native().isoformat()[:10]
    return str(created_at)


def print_legacy_groups_list(legacy_groups: list[dict]) -> None:
    """Print formatted list of legacy groups."""
    print("\nLegacy Groups:")
    print("=" * 60)

    if not legacy_groups:
        print("No legacy groups found")
    else:
        total_episodes = sum(g["episode_count"] for g in legacy_groups)
        total_entities = sum(g["entity_count"] for g in legacy_groups)
        print(
            f"Total: {len(legacy_groups)} groups, {total_entities} entities, {total_episodes} episodes"
        )
        print()

        for group in legacy_groups:
            print(
                f"  {group['group_id']}: {group['entity_count']} entities, {group['episode_count']} episodes"
            )

    print()


def print_group_review(group_id: str, episodes: list[dict]) -> None:
    """Print formatted review of group episodes."""
    print(f"\nReviewing group: {group_id}")
    print("=" * 60)
    print(f"Total episodes: {len(episodes)} (showing first 50)")
    print()

    for i, episode in enumerate(episodes, 1):
        created_at = format_created_at(episode["created_at"])

        print(f"{i}. [{episode['uuid'][:8]}] {episode['name']}")
        print(f"   Created: {created_at}")
        print(f"   Source: {episode['source_description']}")
        print(f"   Content: {episode['content'][:150]}...")
        print()


def print_delete_result(result: dict) -> None:
    """Print formatted deletion result."""
    print(f"\nDeleted group: {result['group_id']}")
    print(f"  Episodes: {result['deleted_episodes']}")
    print(f"  Entities: {result['deleted_entities']}")
    print(f"  Edges: {result['deleted_edges']}")


def print_delete_all_result(result: dict) -> None:
    """Print formatted bulk deletion result."""
    print(f"\nDeleted {result['deleted_groups']} legacy groups")
    print(f"  Total episodes: {result['total_episodes']}")
    print(f"  Total entities: {result['total_entities']}")
