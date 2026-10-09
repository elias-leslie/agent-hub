"""Persisted native-ingestion identities depend on this exact digest format."""

from app.services.session_ingestion.app_server_observations import json_digest


def test_json_digest_is_stable_compact_sorted_ascii_json() -> None:
    # Pinned: source IDs, entity IDs and evidence hashes are stored with this value.
    assert json_digest({"b": [1, "é"], "a": None}) == (
        "a44633ba036df25280e4fd9ef09da6f54dfe6d3611c755e31f993ab16f108f34"
    )
