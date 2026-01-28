"""Database introspection API for development and debugging.

Provides read-only access to database schema and data for:
- Claude Code sessions (via db CLI)
- Autonomous agents (via authenticated API calls)
- Debugging and verification

All operations are read-only. No writes permitted through this API.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db

router = APIRouter(prefix="/admin/db", tags=["admin", "database"])


class TableInfo(BaseModel):
    """Information about a database table."""

    name: str
    row_count: int | None = None


class ColumnInfo(BaseModel):
    """Information about a table column."""

    name: str
    type: str
    nullable: bool
    default: str | None = None
    primary_key: bool = False


class TableSchema(BaseModel):
    """Schema information for a table."""

    name: str
    columns: list[ColumnInfo]
    primary_keys: list[str]
    foreign_keys: list[dict[str, Any]]
    indexes: list[dict[str, Any]]


class QueryResult(BaseModel):
    """Result of a read-only query."""

    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool = False


class TablesResponse(BaseModel):
    """Response for listing tables."""

    tables: list[TableInfo]
    total: int


@router.get("/tables", response_model=TablesResponse)
async def list_tables(
    db: Annotated[AsyncSession, Depends(get_db)],
    include_counts: bool = Query(default=False, description="Include row counts (slower)"),
) -> TablesResponse:
    """List all tables in the database."""

    def _get_tables(connection: Any) -> list[TableInfo]:
        inspector = inspect(connection)
        table_names = inspector.get_table_names()
        tables = []
        for name in sorted(table_names):
            row_count = None
            if include_counts:
                result = connection.execute(text(f'SELECT COUNT(*) FROM "{name}"'))
                row_count = result.scalar()
            tables.append(TableInfo(name=name, row_count=row_count))
        return tables

    tables = await db.run_sync(lambda conn: _get_tables(conn.connection()))
    return TablesResponse(tables=tables, total=len(tables))


@router.get("/tables/{table_name}/schema", response_model=TableSchema)
async def get_table_schema(
    table_name: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TableSchema:
    """Get detailed schema for a specific table."""

    def _get_schema(connection: Any) -> TableSchema:
        inspector = inspect(connection)
        table_names = inspector.get_table_names()

        if table_name not in table_names:
            raise ValueError(f"Table '{table_name}' not found")

        columns = []
        pk_cols = inspector.get_pk_constraint(table_name)
        pk_names = pk_cols.get("constrained_columns", []) if pk_cols else []

        for col in inspector.get_columns(table_name):
            columns.append(
                ColumnInfo(
                    name=col["name"],
                    type=str(col["type"]),
                    nullable=col.get("nullable", True),
                    default=str(col.get("default")) if col.get("default") else None,
                    primary_key=col["name"] in pk_names,
                )
            )

        foreign_keys = []
        for fk in inspector.get_foreign_keys(table_name):
            foreign_keys.append(
                {
                    "columns": fk.get("constrained_columns", []),
                    "referred_table": fk.get("referred_table"),
                    "referred_columns": fk.get("referred_columns", []),
                }
            )

        indexes = []
        for idx in inspector.get_indexes(table_name):
            indexes.append(
                {
                    "name": idx.get("name"),
                    "columns": idx.get("column_names", []),
                    "unique": idx.get("unique", False),
                }
            )

        return TableSchema(
            name=table_name,
            columns=columns,
            primary_keys=pk_names,
            foreign_keys=foreign_keys,
            indexes=indexes,
        )

    try:
        schema = await db.run_sync(lambda conn: _get_schema(conn.connection()))
        return schema
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None


@router.get("/tables/{table_name}/count")
async def get_table_count(
    table_name: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Get row count for a specific table."""

    def _get_count(connection: Any) -> int:
        inspector = inspect(connection)
        if table_name not in inspector.get_table_names():
            raise ValueError(f"Table '{table_name}' not found")
        result = connection.execute(text(f'SELECT COUNT(*) FROM "{table_name}"'))
        return result.scalar()

    try:
        count = await db.run_sync(lambda conn: _get_count(conn.connection()))
        return {"table": table_name, "count": count}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None


@router.get("/query", response_model=QueryResult)
async def execute_query(
    db: Annotated[AsyncSession, Depends(get_db)],
    q: str = Query(..., description="SQL query (SELECT only)"),
    limit: int = Query(default=100, le=1000, description="Max rows to return"),
) -> QueryResult:
    """Execute a read-only SQL query.

    Only SELECT statements are allowed. Results are limited to prevent
    accidental large data transfers.
    """
    normalized = q.strip().upper()
    if not normalized.startswith("SELECT"):
        raise HTTPException(
            status_code=400,
            detail="Only SELECT queries are allowed. Query must start with SELECT.",
        )

    dangerous_keywords = ["INSERT", "UPDATE", "DELETE", "DROP", "TRUNCATE", "ALTER", "CREATE"]
    for keyword in dangerous_keywords:
        # Use word boundary check to avoid false positives (e.g., "created_at" matching "CREATE")
        import re
        if re.search(rf"\b{keyword}\b", normalized):
            raise HTTPException(
                status_code=400,
                detail=f"Query contains forbidden keyword: {keyword}. Only read operations allowed.",
            )

    if "LIMIT" not in normalized:
        q = f"{q.rstrip(';')} LIMIT {limit}"

    try:
        result = await db.execute(text(q))
        columns = list(result.keys())
        rows_raw = result.fetchall()
        rows = [[_serialize_value(v) for v in row] for row in rows_raw]
        truncated = len(rows) >= limit

        return QueryResult(
            columns=columns,
            rows=rows,
            row_count=len(rows),
            truncated=truncated,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Query error: {e!s}") from None


@router.get("/tables/{table_name}/sample")
async def get_table_sample(
    table_name: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=10, le=100, description="Number of rows"),
) -> QueryResult:
    """Get a sample of rows from a table."""

    def _check_table(connection: Any) -> bool:
        inspector = inspect(connection)
        return table_name in inspector.get_table_names()

    exists = await db.run_sync(lambda conn: _check_table(conn.connection()))
    if not exists:
        raise HTTPException(status_code=404, detail=f"Table '{table_name}' not found")

    query = f'SELECT * FROM "{table_name}" LIMIT {limit}'
    result = await db.execute(text(query))
    columns = list(result.keys())
    rows_raw = result.fetchall()
    rows = [[_serialize_value(v) for v in row] for row in rows_raw]

    return QueryResult(
        columns=columns,
        rows=rows,
        row_count=len(rows),
        truncated=len(rows) >= limit,
    )


def _serialize_value(value: Any) -> Any:
    """Serialize a database value to JSON-compatible format."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, dict)):
        return value
    return str(value)
