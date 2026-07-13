"""Lifecycle and resource-bound tests for the voice WebSocket."""

import asyncio
import base64
import json
import logging
from unittest.mock import AsyncMock

import pytest
from fastapi import WebSocketDisconnect

from app.api.endpoints import voice
from app.services.voice.connection_manager import manager


@pytest.fixture(autouse=True)
def reset_voice_connection_state():
    """Keep module-level WebSocket ownership state isolated between tests."""
    voice.recording_states.clear()
    voice.active_recordings_by_client.clear()
    voice.active_recording_ids.clear()
    manager.active_connections.clear()
    manager.session_connections.clear()
    yield
    voice.recording_states.clear()
    voice.active_recordings_by_client.clear()
    voice.active_recording_ids.clear()
    manager.active_connections.clear()
    manager.session_connections.clear()


def _message(message_type: str, **fields: object) -> str:
    return json.dumps({"type": message_type, **fields})


@pytest.mark.asyncio
async def test_audio_over_byte_limit_is_rejected_and_released(monkeypatch):
    monkeypatch.setattr(voice, "MAX_RECORDING_BYTES", 4)
    websocket = AsyncMock()
    state = voice.RecordingState(client_id="client-a")

    await voice._handle_message(
        websocket,
        101,
        state,
        "client-a",
        "aico",
        voice.MODE_TRANSCRIBE,
        _message(voice.MSG_TYPE_CONTROL, action=voice.ACTION_START),
    )
    await voice._handle_message(
        websocket,
        101,
        state,
        "client-a",
        "aico",
        voice.MODE_TRANSCRIBE,
        _message(voice.MSG_TYPE_AUDIO, data=base64.b64encode(b"12345").decode()),
    )

    assert state.audio == bytearray()
    assert state.is_recording is False
    assert voice.active_recording_ids == set()
    assert voice.active_recordings_by_client == {}
    error = websocket.send_json.await_args.args[0]
    assert error["type"] == voice.MSG_TYPE_ERROR
    assert error["code"] == "recording_too_large"


@pytest.mark.asyncio
async def test_elapsed_duration_limit_releases_recording():
    websocket = AsyncMock()
    state = voice.RecordingState(client_id="client-a")
    assert voice._claim_recording(102, state) is None
    assert state.started_at is not None
    state.started_at -= voice.MAX_RECORDING_SECONDS + 1

    await voice._handle_message(
        websocket,
        102,
        state,
        "client-a",
        "aico",
        voice.MODE_TRANSCRIBE,
        _message(voice.MSG_TYPE_AUDIO, data=base64.b64encode(b"12").decode()),
    )

    assert state.is_recording is False
    assert state.audio == bytearray()
    assert websocket.send_json.await_args.args[0]["code"] == "recording_too_long"


@pytest.mark.asyncio
async def test_silent_recording_times_out_without_another_client_message(monkeypatch):
    monkeypatch.setattr(voice, "MAX_RECORDING_SECONDS", 0.01)
    websocket = AsyncMock()

    async def never_sends_message():
        await asyncio.sleep(60)

    websocket.receive_text.side_effect = never_sends_message
    state = voice.RecordingState(client_id="silent-client")
    assert voice._claim_recording(103, state) is None

    result = await voice._receive_voice_message(websocket, 103, state)

    assert result is None
    assert state.is_recording is False
    assert state.audio == bytearray()
    assert voice.active_recording_ids == set()
    assert websocket.send_json.await_args.args[0]["code"] == "recording_too_long"


@pytest.mark.asyncio
async def test_same_identified_client_cannot_record_concurrently():
    first_websocket = AsyncMock()
    second_websocket = AsyncMock()
    first = voice.RecordingState(client_id="same-client")
    second = voice.RecordingState(client_id="same-client")

    await voice._handle_message(
        first_websocket,
        201,
        first,
        "same-client",
        "aico",
        voice.MODE_TRANSCRIBE,
        _message(voice.MSG_TYPE_CONTROL, action=voice.ACTION_START),
    )
    await voice._handle_message(
        second_websocket,
        202,
        second,
        "same-client",
        "aico",
        voice.MODE_TRANSCRIBE,
        _message(voice.MSG_TYPE_CONTROL, action=voice.ACTION_START),
    )

    assert first.is_recording is True
    assert second.is_recording is False
    assert second_websocket.send_json.await_args.args[0]["code"] == "client_recording_limit"

    voice._release_recording(201, first)
    await voice._handle_message(
        second_websocket,
        202,
        second,
        "same-client",
        "aico",
        voice.MODE_TRANSCRIBE,
        _message(voice.MSG_TYPE_CONTROL, action=voice.ACTION_START),
    )
    assert second.is_recording is True


@pytest.mark.asyncio
async def test_global_recording_limit_bounds_spoofed_client_ids(monkeypatch):
    monkeypatch.setattr(voice, "MAX_CONCURRENT_RECORDINGS", 1)
    first = voice.RecordingState(client_id="claimed-client-a")
    second = voice.RecordingState(client_id="claimed-client-b")
    websocket = AsyncMock()

    assert voice._claim_recording(301, first) is None
    await voice._handle_message(
        websocket,
        302,
        second,
        "claimed-client-b",
        "aico",
        voice.MODE_TRANSCRIBE,
        _message(voice.MSG_TYPE_CONTROL, action=voice.ACTION_START),
    )

    assert second.is_recording is False
    assert websocket.send_json.await_args.args[0]["code"] == "server_recording_limit"


@pytest.mark.asyncio
async def test_recording_slot_is_held_until_transcription_finishes(monkeypatch):
    transcription_started = asyncio.Event()
    finish_transcription = asyncio.Event()

    async def blocked_transcription(audio: bytearray) -> None:
        audio.clear()
        transcription_started.set()
        await finish_transcription.wait()

    monkeypatch.setattr(voice, "_transcribe_audio", blocked_transcription)
    first_websocket = AsyncMock()
    second_websocket = AsyncMock()
    first = voice.RecordingState(client_id="same-client")
    second = voice.RecordingState(client_id="same-client")
    assert voice._claim_recording(303, first) is None
    first.audio.extend(b"pcm")

    stop_task = asyncio.create_task(
        voice._handle_stop(
            first_websocket,
            303,
            first,
            "same-client",
            "aico",
            voice.MODE_TRANSCRIBE,
        )
    )
    await transcription_started.wait()

    assert first.audio == bytearray()
    assert first.owns_slot is True
    await voice._handle_message(
        second_websocket,
        304,
        second,
        "same-client",
        "aico",
        voice.MODE_TRANSCRIBE,
        _message(voice.MSG_TYPE_CONTROL, action=voice.ACTION_START),
    )
    assert second_websocket.send_json.await_args.args[0]["code"] == "client_recording_limit"

    finish_transcription.set()
    await stop_task
    assert first.owns_slot is False
    assert voice.active_recording_ids == set()


class _DisconnectingWebSocket:
    """Minimal WebSocket double that proves a buffer existed before disconnect."""

    def __init__(self, *, failure: Exception) -> None:
        self.messages = [
            _message(voice.MSG_TYPE_CONTROL, action=voice.ACTION_START),
            _message(voice.MSG_TYPE_AUDIO, data=base64.b64encode(b"live-audio").decode()),
        ]
        self.failure = failure
        self.saw_buffer_before_failure = False

    async def accept(self) -> None:
        return None

    async def receive_text(self) -> str:
        if self.messages:
            return self.messages.pop(0)
        state = voice.recording_states[id(self)]
        self.saw_buffer_before_failure = state.audio == bytearray(b"live-audio")
        raise self.failure

    async def send_json(self, _message: dict[str, object]) -> None:
        return None


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [WebSocketDisconnect(), RuntimeError("synthetic failure")])
async def test_disconnect_or_receive_error_cleans_all_recording_ownership(failure):
    websocket = _DisconnectingWebSocket(failure=failure)

    await voice.websocket_endpoint(
        websocket,
        user_id="cleanup-client",
        app="aico",
        session_id="cleanup-session",
        mode=voice.MODE_TRANSCRIBE,
    )

    assert websocket.saw_buffer_before_failure is True
    assert voice.recording_states == {}
    assert voice.active_recording_ids == set()
    assert voice.active_recordings_by_client == {}
    assert manager.active_connections == {}
    assert manager.session_connections == {}


@pytest.mark.asyncio
async def test_stop_releases_buffer_and_does_not_log_transcript(monkeypatch, caplog):
    transcript = "never-log-this-private-transcript"
    monkeypatch.setattr(voice, "_transcribe_audio", AsyncMock(return_value=transcript))
    websocket = AsyncMock()
    state = voice.RecordingState(client_id="client-a")
    assert voice._claim_recording(401, state) is None
    state.audio.extend(b"pcm")
    owned_buffer = state.audio

    with caplog.at_level(logging.INFO, logger="agent_hub.api.voice"):
        await voice._handle_stop(
            websocket,
            401,
            state,
            "client-a",
            "aico",
            voice.MODE_TRANSCRIBE,
        )

    assert owned_buffer == bytearray()
    assert state.audio == bytearray()
    assert state.is_recording is False
    assert voice.active_recording_ids == set()
    assert transcript not in caplog.text
    assert websocket.send_json.await_args.args[0] == {
        "type": voice.MSG_TYPE_TRANSCRIPT,
        "data": transcript,
    }


@pytest.mark.asyncio
async def test_old_disconnect_does_not_remove_newer_session_connection():
    first = AsyncMock()
    second = AsyncMock()
    await manager.connect(first, "client", "shared-session")
    await manager.connect(second, "client", "shared-session")

    manager.disconnect(first, "client", "shared-session")

    assert manager.session_connections["shared-session"] is second
