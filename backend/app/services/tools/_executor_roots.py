"""Project root directory proxy for the direct tool executor.

Provides a dict-like proxy over get_known_roots() so callers that import
KNOWN_ROOTS always see the current cached project-root mapping.
"""

from __future__ import annotations


def _get_known_roots() -> dict[str, str]:
    """Get project_id → root_path mapping from cached project data."""
    from app.constants.projects import get_known_roots

    return get_known_roots()


class _RootsProxy(dict):
    """Dict-like proxy that delegates to get_known_roots()."""

    def get(self, key: str, default: str | None = None) -> str | None:
        return _get_known_roots().get(key, default)

    def __getitem__(self, key: str) -> str:
        return _get_known_roots()[key]

    def __contains__(self, key: object) -> bool:
        return key in _get_known_roots()

    def __iter__(self):
        return iter(_get_known_roots())

    def items(self):
        return _get_known_roots().items()

    def values(self):
        return _get_known_roots().values()

    def keys(self):
        return _get_known_roots().keys()

    def __repr__(self) -> str:
        return repr(_get_known_roots())


KNOWN_ROOTS: dict[str, str] = _RootsProxy()
