"""Stable response for retired Memory Curator execution paths."""

from typing import NoReturn

from fastapi import HTTPException


def curator_unavailable() -> NoReturn:
    raise HTTPException(status_code=410, detail="Memory Curator execution is retired; use manual context inventory, preview, edit, and history.")
