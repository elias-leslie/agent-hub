"""Tests for the read-only database query endpoint."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.db import execute_query


class _Result:
    def keys(self) -> list[str]:
        return ["n"]

    def fetchall(self) -> list[tuple[int]]:
        return [(1,)]


class _Session:
    def __init__(self) -> None:
        self.statements: list[str] = []

    async def execute(self, statement: object) -> _Result:
        self.statements.append(str(statement))
        return _Result()


@pytest.mark.asyncio
async def test_query_runs_inside_read_only_transaction() -> None:
    session = _Session()

    result = await execute_query(db=session, q="SELECT nextval('seq') AS n", limit=5)

    assert session.statements == [
        "SET TRANSACTION READ ONLY",
        "SELECT nextval('seq') AS n LIMIT 5",
    ]
    assert result.rows == [[1]]


@pytest.mark.asyncio
async def test_query_rejects_non_select_before_touching_database() -> None:
    session = _Session()

    with pytest.raises(HTTPException):
        await execute_query(db=session, q="DELETE FROM t", limit=5)

    assert session.statements == []
