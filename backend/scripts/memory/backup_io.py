"""
File I/O and serialization utilities for memory backups.
"""

import json
from pathlib import Path
from typing import Any


def convert_neo4j_datetimes(record: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    """
    Convert Neo4j datetime objects to ISO strings.

    Args:
        record: Dictionary containing Neo4j data
        fields: List of field names that may contain datetime objects

    Returns:
        Record with converted datetime fields
    """
    result = dict(record)
    for field in fields:
        if result.get(field) and hasattr(result[field], "to_native"):
            result[field] = result[field].to_native().isoformat()
    return result


def save_json(path: Path, data: dict[str, Any] | list[Any], indent: int = 2) -> None:
    """Save data to JSON file."""
    with open(path, "w") as f:
        json.dump(data, f, indent=indent)


def load_json(path: Path) -> Any:
    """Load data from JSON file."""
    with open(path) as f:
        return json.load(f)


def ensure_backup_dir(backup_dir: Path, backup_name: str) -> Path:
    """
    Create and return backup directory path.

    Args:
        backup_dir: Base backup directory
        backup_name: Name of this backup

    Returns:
        Path to backup directory
    """
    backup_path = backup_dir / backup_name
    backup_path.mkdir(parents=True, exist_ok=True)
    return backup_path
