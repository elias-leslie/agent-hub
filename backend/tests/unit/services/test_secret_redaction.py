"""Secret floor: what is redacted, what is left alone, and every write point that applies it.

Fake credentials are assembled at runtime so no literal token sits in the repo.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.memory_unified import (
    Memory,
    MemoryRevision,
    _redact_memory,
    _redact_memory_revision,
)
from app.models.session import (
    Session,
    SessionEvent,
    SessionSummarySegment,
    _redact_and_compact_session_event,
    _redact_session,
    _redact_summary_segment,
)
from app.services.event_storage import _build_session_event
from app.services.memory.embedder import EmbedderService
from app.services.memory.fingerprint import content_fingerprint
from app.services.memory.privacy_filter import apply_privacy_filter
from app.services.secret_redaction import SECRET_PATTERNS, redact_secrets, redact_text, redact_value


def _pem(edge: str, kind: str = "") -> str:
    return f"-----{edge} {kind}PRIVATE" + " KEY-----"


PEM_BODY = "\n".join(["MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7" + "a" * 12] * 3)
SAMPLES = {
    "private_key": _pem("BEGIN", "RSA ") + "\n" + PEM_BODY + "\n" + _pem("END", "RSA "),
    "aws_access_key": "AK" + "IA" + "Q3EGUTZ7XK4LM2PN",
    "github_token": "gh" + "p_" + "A1b2C3d4" * 5,
    "gitlab_token": "gl" + "pat-" + "x9Y8w7V6u5T4s3R2q1P0",
    "slack_token": "xo" + "xb-" + "1234567890-abcdefABCDEF",
    "anthropic_key": "sk-" + "ant-" + "api03-" + "Zz9_" * 10,
    "stripe_live_key": "sk" + "_live_" + "51HaBcDeFgHiJkLmNoPqRsTu",
}


def _migration(name: str = "b6850500dbfd_redact_secrets_in_session_events"):
    path = Path(__file__).resolve().parents[3] / f"alembic/versions/{name}.py"
    spec = importlib.util.spec_from_file_location("secret_redaction_migration", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(("kind", "secret"), sorted(SAMPLES.items()))
def test_each_kind_is_redacted_in_place(kind: str, secret: str) -> None:
    redacted, counts = redact_secrets(f"export TOKEN='{secret}' # keep this")
    assert redacted == f"export TOKEN='[REDACTED:{kind}]' # keep this"
    assert counts == {kind: 1}


def test_all_floor_kinds_are_covered_by_samples() -> None:
    assert set(SAMPLES) == set(SECRET_PATTERNS)


@pytest.mark.parametrize(
    "secret",
    [
        # Bypass attempts: PEM inside JSON text with escaped newlines, header plus body with no END line,
        # an OpenSSH key, a token glued to a URL or a quote, and a github_pat_ fine-grained token.
        json.dumps({"key": SAMPLES["private_key"]}),
        _pem("BEGIN", "OPENSSH ") + "\n" + PEM_BODY,
        _pem("BEGIN") + "\\n" + PEM_BODY.replace("\n", "\\n"),
        "https://x.example/?token=" + SAMPLES["github_token"] + "&a=1",
        '"' + SAMPLES["anthropic_key"] + '"',
        "github_pat_" + "11ABCDEFG0" + "a1B2c3D4e5" * 8,
    ],
)
def test_bypass_shapes_leave_no_key_material(secret: str) -> None:
    redacted, counts = redact_secrets(secret)
    assert counts
    assert "MIIEvQIBADAN" not in redacted
    for sample in SAMPLES.values():
        assert sample not in redacted
    assert "11ABCDEFG0" not in redacted


@pytest.mark.parametrize(
    "text",
    [
        f"We detect the {_pem('BEGIN')} header in transcripts.",
        "ghp_short",
        "lowercase " + SAMPLES["aws_access_key"].lower(),
        "presigned X-Amz-Credential=AS" + SAMPLES["aws_access_key"][2:] + "%2F20261008",
        "sk_test_" + "51HaBcDeFgHiJkLmNoPqRsTu",
        "plain prose with sk-ant- but nothing after it",
    ],
)
def test_near_misses_are_left_alone(text: str) -> None:
    assert redact_secrets(text) == (text, {})


def test_patterns_stay_linear_on_hostile_input() -> None:
    hostile = (_pem("BEGIN") + " a" * 50 + "\n") * 2000 + "ghp_" + "a" * 30 + " " + "xoxb-" * 20000
    started = time.monotonic()
    redact_secrets(hostile)
    assert time.monotonic() - started < 2


def test_redact_value_walks_json_and_keeps_clean_objects() -> None:
    clean = {"a": ["x", {"b": 1}], "c": None}
    assert redact_value(clean) is clean
    dirty = {"cmd": ["curl", "-H", f"Authorization: Bearer {SAMPLES['github_token']}"], "n": 3}
    redacted = redact_value(dirty)
    assert redacted == {"cmd": ["curl", "-H", "Authorization: Bearer [REDACTED:github_token]"], "n": 3}
    assert SAMPLES["github_token"] in dirty["cmd"][2]  # caller's object is not mutated
    assert redact_text(None) is None


def test_observation_capture_filter_counts_secrets() -> None:
    filtered, stats = apply_privacy_filter(f"<private>x</private> key {SAMPLES['aws_access_key']}")
    assert filtered == "[REDACTED] key [REDACTED:aws_access_key]"
    assert stats == {"private_tags_stripped": 1, "memory_tags_stripped": 0, "secrets_redacted": 1}


def test_session_event_builder_redacts_before_anyone_reads_it() -> None:
    secret = SAMPLES["slack_token"]
    event = _build_session_event(
        "s", 1, 1, "tool_result",
        content=f"out {secret}", tool_input={"command": f"echo {secret}"}, tool_output={"output": f"out {secret}"},
    )
    assert event.content == "out [REDACTED:slack_token]"
    assert event.tool_input == {"command": "echo [REDACTED:slack_token]"}
    # Redaction keeps content and output equal, so compaction still applies.
    assert event.tool_output_from_content is True
    assert event.tool_output == {"output": "out [REDACTED:slack_token]"}


def test_session_event_flush_listener_covers_direct_orm_writes() -> None:
    secret = SAMPLES["stripe_live_key"]
    event = SessionEvent(
        session_id="s", turn=1, sequence=1, event_type="tool_use",
        content=None, tool_input={"env": {"KEY": secret}}, tool_output={"meta": [secret]},
    )
    _redact_and_compact_session_event(None, None, event)
    assert event.content is None
    assert event.tool_input == {"env": {"KEY": "[REDACTED:stripe_live_key]"}}
    assert event.tool_output == {"meta": ["[REDACTED:stripe_live_key]"]}


def test_session_heartbeat_never_stores_a_credential() -> None:
    from app.services.session_live_activity import apply_live_activity_heartbeat

    token = SAMPLES["github_token"]
    session = Session(id="s", project_id="p", provider="claude", model="m", provider_metadata={"sdk": "kept"},
                      workstream_note=f"rotate {token}", summary_oneliner=f"used {token}", summary_git_digest=token)
    apply_live_activity_heartbeat(
        session, heartbeat_at="2026-10-15T23:00:00+00:00", phase="running_tool", status="active",
        summary=f"calling gh with {token}", current_tool_name="Bash",
        current_command=f"GH_TOKEN={token} gh api /user", last_event_type="tool_use",
    )
    _redact_session(None, None, session)
    assert session.provider_metadata is not None
    live = session.provider_metadata["live_activity"]
    assert live["current_command"] == "GH_TOKEN=[REDACTED:github_token] gh api /user"
    assert live["last_command"] == "GH_TOKEN=[REDACTED:github_token] gh api /user"
    assert live["summary"] == "calling gh with [REDACTED:github_token]"
    assert session.provider_metadata["sdk"] == "kept"
    assert session.workstream_note == "rotate [REDACTED:github_token]"
    assert session.summary_oneliner == "used [REDACTED:github_token]"
    assert session.summary_git_digest == "[REDACTED:github_token]"
    clean = {"live_activity": {"current_command": "git status"}}
    untouched = Session(id="c", project_id="p", provider="claude", model="m", provider_metadata=clean)
    _redact_session(None, None, untouched)
    assert untouched.provider_metadata is clean  # unchanged JSON is not rewritten
    segment = SessionSummarySegment(session_id="s", summary_oneliner=f"key {token}", summary_git_digest=None)
    _redact_summary_segment(None, None, segment)
    assert segment.summary_oneliner == "key [REDACTED:github_token]"
    assert segment.summary_git_digest is None


def test_memory_flush_listener_redacts_and_refreshes_fingerprint() -> None:
    raw = f"Use token {SAMPLES['gitlab_token']} for the mirror"
    memory = Memory(content=raw, content_fingerprint=content_fingerprint(raw), name=None,
                    summary=f"token {SAMPLES['gitlab_token']}", source_description=None)
    _redact_memory(None, None, memory)
    assert memory.content == "Use token [REDACTED:gitlab_token] for the mirror"
    assert memory.summary == "token [REDACTED:gitlab_token]"
    assert memory.content_fingerprint == content_fingerprint(memory.content)


def test_memory_revision_listener_redacts_and_rehashes() -> None:
    raw = f"key {SAMPLES['anthropic_key']}"
    revision = MemoryRevision(content=raw, content_hash=hashlib.sha256(raw.encode()).hexdigest(), name=None,
                              summary=None, source_description=None)
    _redact_memory_revision(None, None, revision)
    assert revision.content == "key [REDACTED:anthropic_key]"
    assert revision.content_hash == hashlib.sha256(revision.content.encode()).hexdigest()


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _strings(item)]
    if isinstance(value, list):
        return [text for item in value for text in _strings(item)]
    return []


def test_memory_listeners_redact_metadata_change_reason_and_tags() -> None:
    # compact_content is what context injection prefers over content.
    token = SAMPLES["github_token"]
    metadata = {"compact_content": f"Use {token}", "enrichment": {"topics": [token.lower()], "action_items": [f"fix {token}"]}}
    memory = Memory(content="clean", name=None, summary=None, source_description=None,
                    tags=[f"t-{token}"], metadata_=metadata)
    _redact_memory(None, None, memory)
    assert memory.metadata_ == {
        "compact_content": "Use [REDACTED:github_token]",
        "enrichment": {"topics": ["[REDACTED:github_token]"], "action_items": ["fix [REDACTED:github_token]"]},
    }
    assert memory.tags == ["t-[REDACTED:github_token]"]
    revision = MemoryRevision(content="clean", content_hash="h", name=None, summary=None, source_description=None,
                              change_reason=f"rotated {token}", metadata_=metadata)
    _redact_memory_revision(None, None, revision)
    assert revision.change_reason == "rotated [REDACTED:github_token]"
    assert revision.content_hash == "h"  # content unchanged
    assert not any("A1b2C3d4" in text for text in _strings(revision.metadata_))
    clean = {"compact_content": "fine", "enrichment": {"topics": ["fine"]}}
    untouched = Memory(content="clean", metadata_=clean)
    _redact_memory(None, None, untouched)
    assert untouched.metadata_ is clean  # unchanged JSON is not rewritten


def test_enrichment_never_keeps_credential_fragments() -> None:
    from app.services.memory.enrichment import enrich_memory_content

    token = SAMPLES["github_token"]
    # Truncation (summary at 120, action items at 180) would cut the token below the floor's
    # length, and topics are lowercased; pads put the token across each cut.
    for pad in (100, 150):
        content = f"Fix {'x' * pad} {token} token\nfix the mirror with {token}"
        enrichment = enrich_memory_content(content, source="agent")
        stored = [enrichment.summary or "", *_strings(enrichment.metadata)]
        assert not any("a1b2c3d4" in text.lower() for text in stored), pad
        assert stored[-1] == "fix the mirror with [REDACTED:github_token]"
        assert enrichment.sensitivity_tier == "confidential"  # judged on the original text


@pytest.mark.asyncio
async def test_creator_stores_no_credential_in_content_or_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.memory import episode_creator
    from app.services.memory.ingestion_config import LEARNING

    monkeypatch.setattr(episode_creator, "find_exact_duplicate", AsyncMock(return_value=None))
    repo = MagicMock()
    repo.create = AsyncMock(return_value=SimpleNamespace(id="m1"))
    embedder = MagicMock()
    embedder.embed = AsyncMock(return_value=None)
    raw = f"**Mirror Token**: The mirror pushes with {SAMPLES['github_token']} from the vault."
    result = await episode_creator.create_episode_internal(
        repo, embedder, "project-agent-hub", raw, "n", LEARNING, None, episode_creator.datetime.now(episode_creator.UTC),
        None, None, None, None, None, None, "normal", "test", None,
    )
    assert result.success, result.validation_error
    assert repo.create.await_args and embedder.embed.await_args
    stored = repo.create.await_args.kwargs
    assert stored["metadata"]["compact_content"] == raw.replace(SAMPLES["github_token"], "[REDACTED:github_token]")
    assert not any("A1b2C3d4" in text for text in _strings(stored))
    assert embedder.embed.await_args.args[0] == stored["content"]


@pytest.mark.asyncio
async def test_embedder_never_sends_a_secret() -> None:
    client = MagicMock()
    client.aio.models.embed_content = AsyncMock(
        return_value=SimpleNamespace(embeddings=[SimpleNamespace(values=[0.1])] * 2)
    )
    embedder = EmbedderService(api_key="test-key")
    embedder._clients["test-key"] = client
    await embedder.embed(f"remember {SAMPLES['github_token']}")
    await embedder.embed_batch([f"a {SAMPLES['aws_access_key']}", "clean"])
    sent = [call.kwargs["contents"] for call in client.aio.models.embed_content.await_args_list]
    assert sent == ["remember [REDACTED:github_token]", ["a [REDACTED:aws_access_key]", "clean"]]


@pytest.mark.parametrize("secret", list(SAMPLES.values()))
def test_migration_candidate_regex_preselects_every_floor_match(secret: str) -> None:
    # PostgreSQL's ARE accepts this regex unchanged; Python's re agrees on these classes.
    candidate = re.compile(_migration().CANDIDATE_REGEX)
    assert candidate.search(secret)
    assert candidate.search(json.dumps({"o": secret}))


def test_memory_migration_uses_the_same_candidate_superset() -> None:
    assert _migration("d3a9c1f47e20_redact_secrets_in_memory_rows").CANDIDATE_REGEX == _migration().CANDIDATE_REGEX


def test_migration_redacts_nested_json_and_reports_kinds() -> None:
    from collections import Counter

    kinds: Counter[str] = Counter()
    value = {"output": f"{SAMPLES['private_key']} and {SAMPLES['aws_access_key']}", "rc": 0}
    redacted = _migration()._redact(value, kinds)
    assert redacted == {"output": "[REDACTED:private_key] and [REDACTED:aws_access_key]", "rc": 0}
    assert kinds == {"private_key": 1, "aws_access_key": 1}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_migration_rewrites_only_matching_rows_on_postgres() -> None:
    import os

    import sqlalchemy as sa
    from sqlalchemy.dialects.postgresql import JSONB, UUID
    from sqlalchemy.ext.asyncio import create_async_engine

    url = os.environ.get("TEST_AGENT_HUB_DB_URL")
    if not url:
        pytest.skip("TEST_AGENT_HUB_DB_URL is required for PostgreSQL migration validation")
    parsed_url = sa.make_url(url)
    assert parsed_url.database == "agent_hub_test", "Only the explicit test database is allowed"
    engine = create_async_engine(parsed_url.set(drivername="postgresql+asyncpg"))
    migration = _migration()
    ids = [f"00000000-0000-0000-0000-00000000000{n}" for n in range(1, 5)]

    def verify(connection: sa.Connection) -> None:
        # A connection-local temporary table shadows the application's table; everything rolls back.
        table = sa.Table(
            "session_events", sa.MetaData(), sa.Column("id", UUID(as_uuid=False), primary_key=True),
            sa.Column("content", sa.Text), sa.Column("tool_input", JSONB(none_as_null=True)),
            sa.Column("tool_output", JSONB(none_as_null=True)),
            prefixes=["TEMPORARY"],
        )
        table.create(connection)
        fixtures = [
            {"id": ids[0], "content": f"token {SAMPLES['github_token']}", "tool_input": None, "tool_output": None},
            {"id": ids[1], "content": None, "tool_input": {"cmd": SAMPLES["private_key"]}, "tool_output": {"output": "ok"}},
            # Candidate regex hits but the floor does not (bare header): row stays byte-identical.
            {"id": ids[2], "content": f"the {_pem('BEGIN')} header", "tool_input": None, "tool_output": None},
            {"id": ids[3], "content": "clean", "tool_input": {"a": 1}, "tool_output": None},
        ]
        connection.execute(table.insert(), fixtures)
        changed, totals = migration.redact_rows(connection)
        assert changed == ids[:2]
        assert totals == {"github_token": 1, "private_key": 1}
        rows = {row["id"]: dict(row) for row in connection.execute(sa.select(table)).mappings()}
        assert rows[ids[0]]["content"] == "token [REDACTED:github_token]"
        assert rows[ids[0]]["tool_input"] is None  # SQL NULL stays NULL, not JSON 'null'
        assert connection.scalar(sa.select(sa.func.count()).select_from(table).where(table.c.tool_input.is_(None))) == 2
        assert rows[ids[1]]["tool_input"] == {"cmd": "[REDACTED:private_key]"}
        assert rows[ids[1]]["tool_output"] == {"output": "ok"}
        assert rows[ids[2]] == fixtures[2]
        assert rows[ids[3]] == fixtures[3]
        assert migration.redact_rows(connection) == ([], {})

    try:
        async with engine.connect() as connection:
            await connection.run_sync(verify)
            await connection.rollback()
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_memory_metadata_is_redacted_on_postgres_flush() -> None:
    import uuid

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.db import _get_engine
    from app.models import Base
    from app.services.memory.repository import MemoryRepository

    def isolated_schema(connection) -> None:
        # Same pattern as the context-management integration tests: a throwaway schema, rolled back.
        schema = "secret_floor_test_" + uuid.uuid4().hex
        with Operations.context(MigrationContext.configure(connection)):
            from alembic import op

            op.execute(f'CREATE SCHEMA "{schema}"')
            op.execute(f'SET LOCAL search_path TO "{schema}", public')
            for table in Base.metadata.sorted_tables:
                op.create_table(table.name, *(column._copy() for column in table.columns))

    token = SAMPLES["github_token"]
    async with _get_engine().connect() as connection:
        assert (await connection.execute(text("SELECT current_database()"))).scalar() == "agent_hub_test"
        try:
            await connection.run_sync(isolated_schema)
            async with AsyncSession(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint") as db:
                memory = await MemoryRepository().create(
                    content="Mirror pushes use the vault token.", memory_type="episode", scope="project",
                    scope_id="agent-hub", group_id="project-agent-hub", tags=["mirror"],
                    metadata={"compact_content": f"Use {token}", "enrichment": {"topics": [token.lower()]}},
                    change_reason=f"saved {token}", db=db,
                )
                memory.metadata_ = {**memory.metadata_, "compact_content": f"edited {token}"}  # governance-style edit
                await db.flush()
                pattern = {"p": "gh[pousr]_[A-Za-z0-9]{36}"}
                hits = await db.execute(text(
                    "SELECT (SELECT count(*) FROM memories WHERE metadata::text ~ :p OR content ~ :p)"
                    " + (SELECT count(*) FROM memory_revisions WHERE metadata::text ~ :p OR change_reason ~ :p)"
                ), pattern)
                assert hits.scalar() == 0
                stored = await db.execute(text("SELECT metadata->>'compact_content' FROM memories"))
                assert stored.scalar_one() == "edited [REDACTED:github_token]"
        finally:
            await connection.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_session_heartbeat_is_redacted_on_postgres_flush() -> None:
    import uuid

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.db import _get_engine
    from app.models import Base
    from app.services.session_live_activity import apply_live_activity_heartbeat

    def isolated_schema(connection) -> None:
        schema = "secret_floor_test_" + uuid.uuid4().hex
        with Operations.context(MigrationContext.configure(connection)):
            from alembic import op

            op.execute(f'CREATE SCHEMA "{schema}"')
            op.execute(f'SET LOCAL search_path TO "{schema}", public')
            for table in Base.metadata.sorted_tables:
                op.create_table(table.name, *(column._copy() for column in table.columns))

    token = SAMPLES["github_token"]
    async with _get_engine().connect() as connection:
        assert (await connection.execute(text("SELECT current_database()"))).scalar() == "agent_hub_test"
        try:
            await connection.run_sync(isolated_schema)
            async with AsyncSession(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint") as db:
                session = Session(id=str(uuid.uuid4()), project_id="agent-hub", provider="claude", model="m",
                                  session_type="claude_code", summary_oneliner=f"used {token}")
                db.add(session)
                await db.flush()
                apply_live_activity_heartbeat(  # the update path a hook heartbeat takes
                    session, heartbeat_at="2026-10-15T23:00:00+00:00", summary=f"with {token}",
                    current_command=f"GH_TOKEN={token} gh api /user",
                )
                await db.flush()
                hits = await db.execute(text(
                    "SELECT count(*) FROM sessions WHERE row_to_json(sessions)::text ~ :p"
                ), {"p": "gh[pousr]_[A-Za-z0-9]{36}"})
                assert hits.scalar() == 0
                stored = await db.execute(text(
                    "SELECT provider_metadata->'live_activity'->>'last_command' FROM sessions"
                ))
                assert stored.scalar_one() == "GH_TOKEN=[REDACTED:github_token] gh api /user"
        finally:
            await connection.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_memory_migration_rewrites_only_matching_rows_on_postgres() -> None:
    import os

    import sqlalchemy as sa
    from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
    from sqlalchemy.ext.asyncio import create_async_engine

    url = os.environ.get("TEST_AGENT_HUB_DB_URL")
    if not url:
        pytest.skip("TEST_AGENT_HUB_DB_URL is required for PostgreSQL migration validation")
    parsed_url = sa.make_url(url)
    assert parsed_url.database == "agent_hub_test", "Only the explicit test database is allowed"
    engine = create_async_engine(parsed_url.set(drivername="postgresql+asyncpg"))
    migration = _migration("d3a9c1f47e20_redact_secrets_in_memory_rows")
    token = SAMPLES["github_token"]
    mem_ids = ["00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000002"]
    r1, r2 = "00000000-0000-0000-0000-0000000000a1", "00000000-0000-0000-0000-0000000000a2"

    def verify(connection: sa.Connection) -> None:
        # Connection-local temporary tables shadow the application's tables; everything rolls back.
        text_columns = [sa.Column(name, sa.Text) for name in ("content", "name", "summary", "source_description")]
        memories = sa.Table(
            "memories", sa.MetaData(), sa.Column("id", UUID(as_uuid=False), primary_key=True), *text_columns,
            sa.Column("content_fingerprint", sa.String), sa.Column("tags", ARRAY(sa.String)),
            sa.Column("metadata", JSONB(none_as_null=True)), prefixes=["TEMPORARY"],
        )
        revisions = sa.Table(
            "memory_revisions", sa.MetaData(), sa.Column("id", UUID(as_uuid=False), primary_key=True),
            *(column._copy() for column in text_columns), sa.Column("change_reason", sa.Text),
            sa.Column("content_hash", sa.String), sa.Column("tags", ARRAY(sa.String)),
            sa.Column("metadata", JSONB(none_as_null=True)), prefixes=["TEMPORARY"],
        )
        memories.create(connection)
        revisions.create(connection)
        blank = {"name": None, "summary": None, "source_description": None, "tags": []}
        connection.execute(memories.insert(), [
            {"id": mem_ids[0], "content": f"use {token}", "content_fingerprint": "old", **blank, "metadata": {}},
            {"id": mem_ids[1], "content": "clean", "content_fingerprint": "keep", **blank, "metadata": {"compact_content": "clean"}},
        ])
        connection.execute(revisions.insert(), [
            {"id": r1, "content": "clean", "content_hash": "keep", "change_reason": None, **blank,
             "metadata": {"compact_content": f"Use {token}", "compact_status": "source_ready"}},
            {"id": r2, "content": "clean", "content_hash": "keep", "change_reason": "Episode added", **blank, "metadata": {}},
        ])
        changed, totals = migration.redact_rows(connection)
        assert changed == {"memories": mem_ids[:1], "memory_revisions": [r1]}
        assert totals == {"github_token": 2}
        mem = {row["id"]: dict(row) for row in connection.execute(sa.select(memories)).mappings()}
        assert mem[mem_ids[0]]["content"] == "use [REDACTED:github_token]"
        assert mem[mem_ids[0]]["content_fingerprint"] == content_fingerprint("use [REDACTED:github_token]")
        assert mem[mem_ids[1]]["content_fingerprint"] == "keep"
        rev = {row["id"]: dict(row) for row in connection.execute(sa.select(revisions)).mappings()}
        assert rev[r1]["metadata"] == {"compact_content": "Use [REDACTED:github_token]", "compact_status": "source_ready"}
        assert rev[r1]["content_hash"] == "keep"  # content itself was clean
        assert rev[r2]["change_reason"] == "Episode added"
        assert migration.redact_rows(connection) == ({"memories": [], "memory_revisions": []}, {})

    try:
        async with engine.connect() as connection:
            await connection.run_sync(verify)
            await connection.rollback()
    finally:
        await engine.dispose()
