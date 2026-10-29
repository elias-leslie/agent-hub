"""A run whose history outgrows a small window is compacted mid-run through the real loop, finishes, and its session
keeps every original event plus one ``compaction`` event."""

from __future__ import annotations

import os
from collections import Counter
from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import Enum, make_url, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.schema import CreateTable

from app.api.complete.orchestrator import run_completion
from app.llm.compaction import CompactionPolicy, Compactor, SummaryRequest, SummaryResult
from app.llm.providers.faux import (
    FauxModelDefinition,
    RegisterFauxProviderOptions,
    faux_assistant_message,
    faux_tool_call,
    register_faux_provider,
)
from app.llm.types import Context, TextContent, ToolCall, ToolResultMessage, UserMessage
from app.models import CostLog, Session, SessionEvent
from app.services.workflow_runs.agent_hub_transcript import Transcript, record_transcript
from app.services.workflow_runs.executor_agent_hub import LoopLog

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def pg_db() -> AsyncGenerator[AsyncSession]:
    configured = os.environ.get("TEST_AGENT_HUB_DB_URL")
    if not configured:
        pytest.skip("TEST_AGENT_HUB_DB_URL is required")
    url = make_url(configured).set(drivername="postgresql+asyncpg")
    assert url.database and url.database.endswith("_test")
    engine = create_async_engine(url)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        schema = f"compaction_{uuid4().hex}"
        await connection.execute(text(f"CREATE SCHEMA {schema}"))
        await connection.execute(text(f"SET LOCAL search_path TO {schema}"))

        def create_tables(sync_connection: object) -> None:
            for table in (Session.__table__, SessionEvent.__table__, CostLog.__table__):
                for column in table.columns:
                    if isinstance(column.type, Enum):
                        column.type.create(sync_connection, checkfirst=True)
                sync_connection.execute(CreateTable(table, include_foreign_key_constraints=[]))  # type: ignore[attr-defined]

        await connection.run_sync(create_tables)
        async with AsyncSession(
            bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        ) as session:
            yield session
        await transaction.rollback()
    await engine.dispose()


@pytest.mark.asyncio
async def test_a_small_window_forces_a_compaction_mid_run_and_the_session_keeps_the_originals(pg_db) -> None:
    sid = str(uuid4())
    pg_db.add(Session(id=sid, project_id="agent-hub", provider="faux", model="faux-small", status="active",
                      session_type="agent", request_source="workflow_run"))
    await pg_db.commit()
    reg = register_faux_provider(RegisterFauxProviderOptions(models=[FauxModelDefinition(id="faux-small", context_window=1000)]))
    try:
        calls = [faux_tool_call("read_file", {"path": f"/f{i}"}, id=f"c{i}") for i in range(12)]
        reg.set_responses([faux_assistant_message([c], stop_reason="toolUse") for c in calls] + [faux_assistant_message("all done")])
        model = reg.get_model()
        assert model is not None

        async def summarize(request: SummaryRequest) -> SummaryResult:
            return SummaryResult(text="Goal: read twelve files.", model="fake-summarizer", input_tokens=900, output_tokens=60, cost_usd=0.0004)

        compactor = Compactor(
            CompactionPolicy(context_window=model.context_window, reserve_tokens=200, keep_recent_tokens=250,
                             tool_result_chars=200, read_tools=frozenset({"read_file"})),
            summarize,
        )

        async def run_tool(call: ToolCall) -> ToolResultMessage:
            return ToolResultMessage(tool_call_id=call.id, tool_name=call.name, content=[TextContent(text="y" * 400)], is_error=False, timestamp=0)

        loop_log = LoopLog()
        context = Context(messages=[UserMessage(content="read the files", timestamp=0)], system_prompt="rules")
        result = await run_completion(
            model, context, execute_tools=True, run_tool=run_tool, max_turns=None, on_loop_event=loop_log, compactor=compactor,
        )
        assert [b.text for b in result.message.content if isinstance(b, TextContent)] == ["all done"]
        assert result.turns == 13

        await record_transcript(
            pg_db,
            Transcript(sid, "coder", "faux-small", input_messages=({"role": "user", "content": "read the files"},),
                       turns=result.usage_messages, tool_results=loop_log.tool_results),
        )
        await pg_db.commit()
    finally:
        reg.unregister()

    events = (await pg_db.execute(select(SessionEvent).where(SessionEvent.session_id == sid))).scalars().all()
    kinds = Counter(str(getattr(e.event_type, "value", e.event_type)) for e in events)
    assert kinds["tool_use"] == 12 and kinds["tool_result"] == 12 and kinds["user_message"] == 1  # nothing recorded was dropped
    compactions = [e for e in events if e.event_type == "compaction"]
    assert compactions, "the run must have been compacted"
    event = compactions[0]
    assert event.content.startswith("Context compacted: ") and event.model_used == "fake-summarizer"
    assert event.tool_output["tokens_before"] > event.tool_output["tokens_after"]
    costs = (await pg_db.execute(select(CostLog).where(CostLog.session_id == sid, CostLog.model == "fake-summarizer"))).scalars().all()
    assert costs and costs[0].input_tokens == 900
