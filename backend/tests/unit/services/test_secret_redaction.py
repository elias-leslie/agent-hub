"""Secret floor: what is redacted, what is left alone, and every write point that applies it.

Fake credentials are assembled at runtime so no literal token sits in the repo.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from collections.abc import Callable
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
from app.models.native_observation import (
    NativeCommandEntity,
    NativeObservationIssue,
    NativeObservationReceipt,
    _redact_command_entity,
    _redact_observation_issue,
    _redact_observation_receipt,
)
from app.models.session import (
    Session,
    SessionEvent,
    SessionSummarySegment,
    _redact_and_compact_session_event,
    _redact_session,
    _redact_summary_segment,
)
from app.services.event_storage import _build_session_event, _extract_tool_result_content
from app.services.memory.embedder import EmbedderService
from app.services.memory.fingerprint import content_fingerprint
from app.services.memory.privacy_filter import apply_privacy_filter
from app.services.secret_redaction import SECRET_PATTERNS, redact_secrets, redact_text, redact_value
from tests.linear_time import assert_linear


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


@pytest.mark.parametrize("kind", sorted(set(SAMPLES) - {"private_key"}))
@pytest.mark.parametrize(
    ("before", "after"),
    [
        # Escapes and URL encoding put a letter or digit right before the token (JSON text from
        # jq -c or an API body, a percent-encoded query); a following '_' or letter must not save it.
        ("a\\n", ""),
        ("x\\r\\n", ""),
        ("\\t", ""),
        ("\\u0022", "\\u0022"),
        ("token%3D", "%26a%3D1"),
        ("", "_x"),
        ("=", "abc"),
        # Rarer escapes: \x22, \f, \v, \0, octal \042, \U00000022 and a double-encoded %253D.
        ("a\\x22", ""),
        ("a\\f", ""),
        ("a\\v", ""),
        ("a\\0", ""),
        ("a\\042", ""),
        ("a\\U00000022", ""),
        ("token%253D", ""),
        # Terminal colour codes end in a letter: grep --color=always, raw or JSON-escaped.
        ("\x1b[32m", "\x1b[0m"),
        ("\x1b[1m", ""),
        (":\x1b[01;31m\x1b[K", "\x1b[m\x1b[K"),
        ("a\\u001b[0m", ""),
        ("a\\x1b[31m", ""),
        ("a\\033[1;32m", ""),
        # A combined truecolor code runs past 20 parameter bytes; two codes back to back; the tail
        # of a code whose start sat in the previous chunk; the 8-bit CSI; an OSC 8 link's escaped BEL.
        ("\x1b[38;2;255;255;255;48;2;0;0;0m", "\x1b[0m"),
        ("a\x1b[38;2;255;255;255;48;2;0;0;0;1;3;4;9m", ""),
        ("a\\u001b[38;2;255;255;255;48;2;0;0;0m", ""),
        ("a\\e[38;5;196;48;5;232;1;4m", ""),
        ("\x1b[38;2;255;255;255m\x1b[48;2;0;0;0m", "\x1b[39;49m"),
        ("5;255m", ""),
        ("a\x9b1;31m", ""),
        ("x\\a", ""),
        # JSON inside JSON doubles the backslash; the 8-bit CSI written out.
        ("a\\\\u001b[38;2;255;255;255;48;2;0;0;0m", ""),
        ("a\\u009b1;31m", ""),
        ("a\\x9b1m", ""),
    ],
)
def test_escaped_or_glued_tokens_are_redacted(kind: str, before: str, after: str) -> None:
    secret = SAMPLES[kind]
    if after[:1].isalnum() and kind == "aws_access_key":
        after = after.lower()  # an uppercase run would make it a longer id, not an access key
    redacted, counts = redact_secrets(f"{before}{secret}{after}")
    assert counts == {kind: 1}
    # Token classes that allow '_' or letters take the suffix with them; nothing else is lost.
    assert redacted.startswith(f"{before}[REDACTED:{kind}]")
    assert secret not in redacted


@pytest.mark.parametrize("kind", sorted(set(SAMPLES) - {"private_key"}))
def test_tokens_in_osc8_hyperlinks_are_redacted(kind: str) -> None:
    secret = SAMPLES[kind]
    raw = f"\x1b]8;;https://x.example/?t={secret}\x1b\\{secret}\x1b]8;;\x1b\\ \x1b]8;id=1;{secret}\x07{secret}\x1b]8;;\x07"
    for text in (raw, json.dumps(raw)):
        redacted, counts = redact_secrets(text)
        assert counts == {kind: 4}
        assert secret not in redacted
    redacted, _ = redact_secrets(raw)
    assert redacted.startswith(f"\x1b]8;;https://x.example/?t=[REDACTED:{kind}]\x1b\\[REDACTED:{kind}]\x1b]8;;\x1b\\")


@pytest.mark.parametrize("kind", sorted(set(SAMPLES) - {"private_key"}))
@pytest.mark.parametrize("cut", [5, 9, 14])
def test_tokens_cut_apart_by_colour_codes_are_redacted(kind: str, cut: int) -> None:
    # rg or grep --color=always highlights the searched part of a token; the codes stay, the token goes.
    secret = SAMPLES[kind]
    head, tail = secret[:cut], secret[cut:]
    shapes = [
        (f"f:\x1b[0m\x1b[1m\x1b[31m{head}\x1b[0m{tail} x", f"f:\x1b[0m\x1b[1m\x1b[31m[REDACTED:{kind}]\x1b[0m x"),
        (f"\x1b[01;31m\x1b[K{head}\x1b[m\x1b[K{tail}", f"\x1b[01;31m\x1b[K[REDACTED:{kind}]\x1b[m\x1b[K"),
        (f"a\x1b[1m{head}\x1b[38;2;255;255;255;48;2;0;0;0m{tail}", f"a\x1b[1m[REDACTED:{kind}]\x1b[38;2;255;255;255;48;2;0;0;0m"),
        (f"=\\u001b[1m{head}\\u001b[0m{tail}", f"=\\u001b[1m[REDACTED:{kind}]\\u001b[0m"),
    ]
    for text, expected in shapes:
        assert redact_secrets(text) == (expected, {kind: 1})


@pytest.mark.parametrize("kind", sorted(set(SAMPLES) - {"private_key"}))
@pytest.mark.parametrize(
    "code",
    [
        "\\\\u001b[0m",  # JSON inside JSON
        "\\" * 15 + "u001b[0m",  # four levels in
        "\\" * 63 + "u001b[0m",
        "\\\\x1b[1;31m",
        "\\\\e[0m",
        "\\u009b1m",  # the 8-bit CSI, written out
        "\\x9b1m",
        "\\x9B38;2;255;255;255;48;2;0;0;0m",
        "\\2331m",
        "\\\\u009b0m",
    ],
)
def test_tokens_cut_by_escaped_codes_are_redacted(kind: str, code: str) -> None:
    secret = SAMPLES[kind]
    for cut in (5, 9):
        redacted, counts = redact_secrets(f"x {secret[:cut]}{code}{secret[cut:]} y")
        assert (redacted, counts) == (f"x [REDACTED:{kind}]{code} y", {kind: 1})


@pytest.mark.parametrize("kind", sorted(set(SAMPLES) - {"private_key"}))
@pytest.mark.parametrize(
    "code",
    [
        "\x1b[1m\x1b(B\x1b[m",  # terminfo sgr0, what $(tput sgr0) writes
        "\x1b(B",
        "\x1b7",
        "\x1b=",
        "\x1b]8;;file:///x\x1b\\",  # an OSC 8 link opening inside the token
        "\x1b]8;id=1;https://x.example/a\x07",
        "\x1b]8;;\x1b\\",  # and closing
        "\x1b]0;title\x1b\\",
        "\x1b]2;title\x07\x1b[0m",
        "\x9d8;;x\x9c",
        "\x1b\\",  # a stray ST
    ],
)
def test_tokens_cut_by_other_escapes_are_redacted(kind: str, code: str) -> None:
    # Each JSON level writes the codes out with more backslashes; the floor must take all of them.
    secret = SAMPLES[kind]
    shapes = [(f"x {secret[:cut]}{code}{secret[cut:]} y", f"x [REDACTED:{kind}]{code} y") for cut in (5, 9)]
    # A whole token right after the code: ESC ( B and ESC 7 leave a letter or digit before it.
    shapes.append((f"x {code}{secret} y", f"x {code}[REDACTED:{kind}] y"))
    for text, expected in shapes:
        for _level in range(5):
            assert redact_secrets(text) == (expected, {kind: 1}), text
            text, expected = json.dumps(text), json.dumps(expected)


@pytest.mark.parametrize("kind", sorted(set(SAMPLES) - {"private_key"}))
def test_token_inside_an_osc8_link_cut_by_its_open_and_close_is_redacted(kind: str) -> None:
    secret = SAMPLES[kind]
    raw = f"see {secret[:6]}\x1b]8;;file:///k\x1b\\{secret[6:12]}\x1b]8;;\x1b\\{secret[12:]}\x1b[0m."
    want = f"see [REDACTED:{kind}]\x1b]8;;file:///k\x1b\\\x1b]8;;\x1b\\\x1b[0m."
    for _level in range(4):
        assert redact_secrets(raw) == (want, {kind: 1})
        raw, want = json.dumps(raw), json.dumps(want)


def test_written_out_terminator_keeps_the_next_codes_backslashes() -> None:
    # ST then a colour code, written out: the OSC must take only its own backslashes.
    secret = SAMPLES["github_token"]
    raw = f"{secret[:7]}\x1b]8;;x\x1b\\\x1b[1m{secret[7:]}\x1b]8;;x\x07\x1b(B{secret}"
    want = "[REDACTED:github_token]\x1b]8;;x\x1b\\\x1b[1m\x1b]8;;x\x07\x1b(B[REDACTED:github_token]"
    for _level in range(4):
        redacted, counts = redact_secrets(raw)
        assert (redacted, counts) == (want, {"github_token": 2})
        raw, want = json.dumps(raw), json.dumps(want)


@pytest.mark.parametrize("kind", sorted(set(SAMPLES) - {"private_key"}))
def test_tokens_cut_by_codes_in_nested_json_are_redacted(kind: str) -> None:
    # A transcript of a tool result that already held JSON-escaped colour codes, dumped again.
    secret = SAMPLES[kind]
    for raw in (
        f"f:\x1b[1;31m{secret[:6]}\x1b[0m{secret[6:]}",
        f"f:\\u001b[1;31m{secret[:6]}\\u001b[0m{secret[6:]}",
        f"f:\x9b31m{secret[:6]}\x9b0m{secret[6:]}",
    ):
        text = raw
        for _level in range(6):
            text = json.dumps(text)
            redacted, counts = redact_secrets(text)
            assert counts == {kind: 1}, text
            assert secret[6:] not in redacted and secret[:6] not in redacted


@pytest.mark.parametrize("first", sorted(set(SAMPLES) - {"private_key"}))
@pytest.mark.parametrize("second", sorted(set(SAMPLES) - {"private_key"}))
@pytest.mark.parametrize("sep", ["\x1b[0m", "\x1b[0m\x1b[1m\x1b[31m", "\\u001b[0m"])
def test_adjacent_tokens_split_by_a_code_are_both_redacted(first: str, second: str, sep: str) -> None:
    # With the code removed, the first token's body would run on into the second one's prefix
    # (ghp, sk, github) and the split pass would leave the second body in the clear.
    one, two = SAMPLES[first], SAMPLES[second].replace("A1b2", "Q7r8").replace("51Ha", "77Zq")
    redacted, counts = redact_secrets(f"f:\x1b[1m\x1b[31m{one}{sep}{two}\x1b[0m x")
    assert redacted == f"f:\x1b[1m\x1b[31m[REDACTED:{first}]{sep}[REDACTED:{second}]\x1b[0m x"
    assert sum(counts.values()) == 2


def test_adjacent_tokens_each_split_by_highlighting_are_both_redacted() -> None:
    one, two = "ghp_" + "A" * 36, "ghp_" + "B" * 36
    text = f"{one[:8]}\x1b[31m{one[8:]}\x1b[0m{two[:6]}\x1b[31m{two[6:]}\x1b[0m"
    redacted, counts = redact_secrets(text)
    assert redacted == "[REDACTED:github_token]\x1b[31m\x1b[0m[REDACTED:github_token]\x1b[31m\x1b[0m"
    assert counts == {"github_token": 2}


def test_key_body_then_a_code_then_a_token_redacts_both() -> None:
    text = _pem("BEGIN") + "\n" + PEM_BODY + "\x1b[0m" + SAMPLES["github_token"]
    redacted, counts = redact_secrets(text)
    assert counts == {"private_key": 1, "github_token": 1}
    assert redacted.endswith("\x1b[0m[REDACTED:github_token]")


def test_coloured_diff_of_a_key_file_is_redacted() -> None:
    lines = SAMPLES["private_key"].split("\n")
    diff = "\x1b[1mdiff --git a/k b/k\x1b[m\n" + "".join(f"\x1b[32m+{line}\x1b[m\n" for line in lines)
    redacted, counts = redact_secrets(diff)
    assert counts == {"private_key": 1}
    assert "MIIEvQIBADAN" not in redacted
    assert redacted.startswith("\x1b[1mdiff --git a/k b/k\x1b[m\n\x1b[32m+[REDACTED:private_key]\x1b[m\x1b[32m")


def test_tool_result_content_is_redacted_before_the_cut() -> None:
    # A token straddling offset 2000 would leave a fragment shorter than the floor's minimum.
    for secret in SAMPLES.values():
        text = "a" * 1985 + " " + secret
        for output in ({"result": text}, {"stdout": text}):
            content = _extract_tool_result_content(output)
            assert content is not None and len(content) <= 2000
            assert content.startswith("a" * 1985 + " [REDACTED")
            assert secret[:9] not in content


@pytest.mark.parametrize(
    "text",
    [
        f"We detect the {_pem('BEGIN')} header in transcripts.",
        "id_" + SAMPLES["github_token"],  # inside a longer identifier
        SAMPLES["aws_access_key"] + "Q",  # 21-character uppercase id
        "ghp_short",
        "lowercase " + SAMPLES["aws_access_key"].lower(),
        "presigned X-Amz-Credential=AS" + SAMPLES["aws_access_key"][2:] + "%2F20261008",
        "sk_test_" + "51HaBcDeFgHiJkLmNoPqRsTu",
        "plain prose with sk-ant- but nothing after it",
        "id_" + SAMPLES["github_token"][:6] + "\x1b[0m" + SAMPLES["github_token"][6:],  # cut, still inside an identifier
        "\x1b[38;2;255;255;255;48;2;0;0;0mghp_short\x1b[0m",
        "id_" + SAMPLES["github_token"][:6] + "\x1b(B" + SAMPLES["github_token"][6:],
        "\x1b]8;;file:///ghp_short\x1b\\ghp_\x1b(Bshort\x1b7",
        "C:\\\\every\\\\ghp_" + "\\\\eA" * 12,  # written-out \e followed by text, no token
    ],
)
def test_near_misses_are_left_alone(text: str) -> None:
    assert redact_secrets(text) == (text, {})


# Each builder takes a repeat count; the case's size is the full input timed against one eighth of it.
# Built per case so collection does not hold megabytes of hostile text in every worker.
_HOSTILE_INPUTS: dict[str, tuple[Callable[[int], str], int]] = {
    # Full size: the PEM body bound (8 KB) is reached only on inputs well past it.
    "pem_headers_tokens_and_slack_prefixes": (
        lambda n: (_pem("BEGIN") + " a" * 50 + "\n") * n + "ghp_" + "a" * 30 + " " + "xoxb-" * (10 * n),
        2000,
    ),
    # Codes of any length and many codes: an unterminated parameter run, then many cut points.
    "unterminated_csi_parameters": (lambda n: "\x1b[" + "1;" * n + SAMPLES["github_token"], 25_000),
    "many_cut_points": (lambda n: ("a\x1b[1mghp_\x1b[0m") * n, 6_400),
    "backslash_run_without_introducer": (lambda n: "\\" * n + SAMPLES["github_token"], 6_400),
    "escaped_csi_introducers": (lambda n: ("\\" * 15 + "u009b") * n, 2_400),
    "osc_openings_without_terminator": (lambda n: "\x1b]" * n, 25_000),
    "long_unterminated_osc": (lambda n: "\x1b]" + "a" * n + SAMPLES["github_token"], 50_000),
    "escaped_osc_hyperlinks": (lambda n: ("\\\\u001b]8;;" + "x" * 2000) * n, 32),
    "escaped_osc_introducers": (lambda n: ("\\" * 15 + "u001b]") * n, 2_400),
    "unending_nf_escape": (lambda n: "\x1b" + " " * n, 50_000),
    "charset_escapes_inside_tokens": (lambda n: ("ghp_AA\x1b(B" + "A" * 34) * n, 1_280),
}


@pytest.mark.parametrize(("build", "size"), list(_HOSTILE_INPUTS.values()), ids=list(_HOSTILE_INPUTS))
def test_patterns_stay_linear_on_hostile_input(build: Callable[[int], str], size: int) -> None:
    assert_linear(redact_secrets, build, size)


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



def test_native_observation_listeners_never_store_a_credential() -> None:
    # Codex native receipts keep the raw command and its stdout/stderr/aggregatedOutput.
    token = SAMPLES["github_token"]
    item = {"command": f"GH_TOKEN={token} gh api /user", "aggregatedOutput": f"\x1b[32m{token}\x1b[0m", "stdout": token}
    receipt = NativeObservationReceipt(source_id="s", position=1, payload_hash="h", observation={"payload": {"item": item}},
                                       normalized={"kind": "command_execution", "note": token}, disposition="accounted")
    _redact_observation_receipt(None, None, receipt)
    issue = NativeObservationIssue(id="i", source_id="s", position=1, code="c", observation={"payload": {"item": item}})
    _redact_observation_issue(None, None, issue)
    entity = NativeCommandEntity(id="e", session_id="s", namespace="n", thread_id="t", turn_id="u", item_id="i",
                                 status="completed", command={"command": item["command"], "cwd": "/tmp"})
    _redact_command_entity(None, None, entity)
    for stored in (receipt.observation, receipt.normalized, issue.observation, entity.command):
        assert all(token not in text for text in _strings(stored))
    assert receipt.observation["payload"]["item"]["aggregatedOutput"] == "\x1b[32m[REDACTED:github_token]\x1b[0m"
    assert entity.command == {"command": "GH_TOKEN=[REDACTED:github_token] gh api /user", "cwd": "/tmp"}
    clean = {"payload": {"item": {"command": "git status"}}}
    untouched = NativeObservationReceipt(source_id="s", position=2, payload_hash="h", observation=clean, normalized=None, disposition="retained")
    _redact_observation_receipt(None, None, untouched)
    assert untouched.observation is clean and untouched.normalized is None  # unchanged JSON is not rewritten

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
