"""Contract for the Claude Fable 5.1 deactivation migration (b7f1c2d3e4a5)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from app.constants.catalog_entries import MODEL_CATALOG
from app.models.model_catalog import ModelCatalogEntry

_PATH = Path(__file__).resolve().parents[1] / "alembic/versions/b7f1c2d3e4a5_make_claude_fable_unroutable.py"


def _migration():
    spec = importlib.util.spec_from_file_location(_PATH.stem, _PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upgrade_deactivates_and_downgrade_restores_exactly():
    module = _migration()
    assert module.down_revision == "43f0a2fd606f"
    assert module._BEFORE["is_active"] is True
    assert module._AFTER["is_active"] is False
    assert set(module._BEFORE) == set(module._AFTER)


def test_text_fits_catalog_columns():
    module = _migration()
    for column in ("hint", "availability"):
        limit = getattr(ModelCatalogEntry.__table__.c[column].type, "length", None)
        assert limit
        assert len(module._AFTER[column]) <= limit
        assert len(module._BEFORE[column]) <= limit


def test_seed_catalog_cannot_recreate_fable():
    assert all(entry.id != "claude-fable-5-1" for entry in MODEL_CATALOG)
