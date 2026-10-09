"""Tests for the SDK-backed ST completion helper."""

from __future__ import annotations

import base64
from types import SimpleNamespace
from typing import ClassVar

import pytest
import typer
from agent_hub.models import StreamChunk
from agent_hub_st import completion
from agent_hub_st.complete import app as complete_app
from agent_hub_st.completion import build_message, encode_audio
from typer.testing import CliRunner


@pytest.mark.parametrize(
    ("suffix", "media_type"),
    [
        (".wav", "audio/wav"),
        (".mp3", "audio/mpeg"),
        (".aif", "audio/aiff"),
        (".aiff", "audio/aiff"),
        (".aac", "audio/aac"),
        (".ogg", "audio/ogg"),
        (".flac", "audio/flac"),
    ],
)
def test_encode_audio_emits_typed_base64_block(tmp_path, suffix: str, media_type: str) -> None:
    audio_path = tmp_path / f"clip{suffix}"
    audio_path.write_bytes(b"audio-bytes")

    block = encode_audio(str(audio_path))

    assert block["type"] == "audio"
    assert block["source"]["type"] == "base64"
    assert block["source"]["media_type"] == media_type
    assert base64.b64decode(block["source"]["data"]) == b"audio-bytes"


def test_encode_audio_rejects_unsupported_extension(tmp_path) -> None:
    audio_path = tmp_path / "clip.m4a"
    audio_path.write_bytes(b"not-supported")

    with pytest.raises(typer.Exit):
        encode_audio(str(audio_path))


def test_message_keeps_images_and_adds_typed_audio(tmp_path) -> None:
    image_path = tmp_path / "frame.png"
    image_path.write_bytes(b"image")
    audio_path = tmp_path / "mix.wav"
    audio_path.write_bytes(b"audio")

    content = build_message("Review both", [str(image_path)], [str(audio_path)])["content"]

    assert [block["type"] for block in content] == ["image", "audio", "text"]
    assert content[1]["source"]["media_type"] == "audio/wav"


def test_complete_help_exposes_audio_without_removing_image() -> None:
    runner = CliRunner()

    complete_help = runner.invoke(complete_app, ["--help"])

    assert complete_help.exit_code == 0
    assert "--audio" in complete_help.output
    assert "-A" in complete_help.output
    assert "--image" in complete_help.output


class _FakeClient:
    """Stands in for the SDK client and records the canonical call."""

    calls: ClassVar[list[tuple[str, list, dict]]] = []

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None

    def complete(self, messages, **options):
        self.calls.append(("complete", messages, options))
        return SimpleNamespace(model_dump=lambda mode: {"content": "ok", "fallback_used": False})

    def stream_sse(self, messages, **options):
        self.calls.append(("stream", messages, options))
        yield StreamChunk(type="content", content="o")
        yield StreamChunk(type="content", content="k")
        yield StreamChunk(type="done", finish_reason="stop", fallback_used=False, session_id="s1")


@pytest.fixture
def sdk(monkeypatch):
    _FakeClient.calls = []
    monkeypatch.setattr(completion, "AgentHubClient", _FakeClient)
    monkeypatch.setattr(completion, "load_credentials", lambda default_source: ("cid", "src"))
    monkeypatch.setattr(completion, "get_agent_hub_url", lambda: "http://hub")
    return _FakeClient


def test_call_complete_goes_through_the_sdk_with_agentic_metadata(sdk) -> None:
    result = completion.call_complete(
        "explorer", "Inspect only", "portfolio-ai", use_memory=False, working_dir="/repo",
        trace_id="trace-1", execute_tools=True, max_turns=5000, parent_session_id="parent-1",
        read_only=True, task_type="heartbeat",
    )
    kind, messages, options = sdk.calls[0]
    assert kind == "complete" and result == {"content": "ok", "fallback_used": False}
    assert messages == [{"role": "user", "content": "Inspect only"}]
    assert options["use_memory"] is False and options["execute_tools"] is True
    assert options["max_turns"] == 5000 and options["working_dir"] == "/repo"
    assert options["parent_session_id"] == "parent-1" and options["read_only"] is True
    assert options["task_type"] == "heartbeat" and options["agent_slug"] == "explorer"


def test_streaming_returns_the_done_evidence_with_full_text(sdk, capsys) -> None:
    result = completion.call_complete("chat", "hi", stream=True)
    assert result["content"] == "ok"
    assert result["fallback_used"] is False and result["session_id"] == "s1"
    assert capsys.readouterr().out == "ok\n"


def test_an_agent_slug_is_required(sdk) -> None:
    with pytest.raises(typer.Exit):
        completion.call_complete(None, "hi")
    assert sdk.calls == []
