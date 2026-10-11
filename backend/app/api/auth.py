"""Caller identity for the dashboard proxy."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.core.access_identity import resolve_caller

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me")
async def auth_me(request: Request) -> dict[str, object]:
    caller = resolve_caller(request)
    return {"email": caller.email, "is_owner": caller.is_owner, "is_local_bypass": caller.is_local_bypass}
