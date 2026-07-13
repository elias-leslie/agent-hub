import asyncio
import base64
import binascii
import json
import logging
import os
import tempfile
import time
import wave
from dataclasses import dataclass, field

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from pydantic import BaseModel

from app.services.completion import CompletionSource, complete_with_memory
from app.services.voice.connection_manager import manager
from app.services.voice.stt import stt_service
from app.services.voice.tts import list_voices, tts_service

logger = logging.getLogger("agent_hub.api.voice")

# Message type constants
MSG_TYPE_AUDIO = "audio"
MSG_TYPE_CONTROL = "control"
MSG_TYPE_TEXT = "text"
MSG_TYPE_TRANSCRIPT = "transcript"
MSG_TYPE_RESPONSE = "response"
MSG_TYPE_ERROR = "error"

# Control action constants
ACTION_START = "start"
ACTION_STOP = "stop"

# Mode constants
MODE_TRANSCRIBE = "transcribe"

# WAV audio format constants
WAV_CHANNELS = 1
WAV_SAMPLE_WIDTH = 2  # 16-bit
WAV_FRAME_RATE = 16000

# A voice turn is one native Whisper context window. At the wire format above,
# 30 seconds is exactly 960,000 raw PCM bytes:
#   30s * 16,000 frames/s * 1 channel * 2 bytes/frame
# Bounding both elapsed time and bytes is intentional: a slow sender cannot hold
# a recording slot forever, and a fast sender cannot exhaust memory before the
# elapsed-time limit is reached.
MAX_RECORDING_SECONDS = 30.0
PCM_BYTES_PER_SECOND = WAV_FRAME_RATE * WAV_CHANNELS * WAV_SAMPLE_WIDTH
MAX_RECORDING_BYTES = int(MAX_RECORDING_SECONDS * PCM_BYTES_PER_SECOND)

# One identified client represents one microphone/user and therefore owns at
# most one active push-to-talk turn. The global ceiling follows Python's default
# asyncio thread-pool capacity, which is also the executor used for STT below.
# It bounds aggregate buffered PCM to <= ~30.7 MB even on the largest pool.
MAX_CONCURRENT_RECORDINGS_PER_CLIENT = 1
MAX_CONCURRENT_RECORDINGS = min(32, (os.process_cpu_count() or 1) + 4)

# Fallback response when AI completion fails
FALLBACK_RESPONSE = "I'm sorry, I had trouble processing that. Could you try again?"

# Voice-specific system prompts by app
VOICE_SYSTEM_PROMPTS = {
    "summitflow": (
        "You are a helpful voice assistant for SummitFlow, a task management system. "
        "Keep responses concise and conversational - the user is speaking to you via audio. "
        "Avoid lists, code blocks, and markdown formatting. Be direct and helpful."
    ),
    "portfolio": (
        "You are a helpful voice assistant for Portfolio AI. "
        "Keep responses concise and conversational - the user is speaking to you via audio. "
        "Avoid lists, code blocks, and markdown formatting. Be direct and helpful."
    ),
    "default": (
        "You are a helpful voice assistant. "
        "Keep responses concise and conversational - the user is speaking to you via audio. "
        "Avoid lists, code blocks, and markdown formatting. Be direct and helpful."
    ),
}

router = APIRouter()


class TTSRequest(BaseModel):
    text: str
    voice: str | None = None  # alias ("male") or full ID ("en-US-GuyNeural")


@router.get("/voices")
async def get_voices(locale: str = "en") -> dict:
    """List available TTS voices, optionally filtered by locale prefix."""
    voices = await list_voices(locale_prefix=locale)
    return {"voices": voices}


@router.post("/tts")
async def text_to_speech(request: TTSRequest) -> Response:
    """Convert text to speech, returns MP3 audio.

    Uses persona.voice_id as fallback when no voice is specified.
    Returns 403 if persona.voice_enabled is False.
    """
    from fastapi import HTTPException

    from app.db import async_session
    from app.services.persona_service import get_persona

    async with async_session() as db:
        persona = await get_persona(db)

    if persona and not persona.voice_enabled:
        raise HTTPException(status_code=403, detail="Voice is disabled in persona settings")

    # Use persona.voice_id as default when no explicit voice
    voice = request.voice
    if not voice and persona and persona.voice_id:
        voice = persona.voice_id

    audio_bytes = await tts_service.synthesize(request.text, voice)
    return Response(content=audio_bytes, media_type="audio/mpeg")


@dataclass
class RecordingState:
    """Bounded, explicitly owned recording state for one WebSocket."""

    client_id: str
    audio: bytearray = field(default_factory=bytearray)
    started_at: float | None = None
    owns_slot: bool = False

    @property
    def is_recording(self) -> bool:
        return self.started_at is not None


# WebSocket IDs own their state; the second index enforces per-client limits.
# ``user_id`` is currently caller-supplied rather than authenticated, so the
# global limit is required as a hard backstop until voice WebSocket auth exists.
recording_states: dict[int, RecordingState] = {}
active_recordings_by_client: dict[str, set[int]] = {}
active_recording_ids: set[int] = set()


def _release_recording(ws_id: int, state: RecordingState) -> None:
    """Release a recording slot and drop the buffer allocation immediately."""
    state.audio = bytearray()
    state.started_at = None
    state.owns_slot = False
    active_recording_ids.discard(ws_id)

    client_recordings = active_recordings_by_client.get(state.client_id)
    if client_recordings is not None:
        client_recordings.discard(ws_id)
        if not client_recordings:
            active_recordings_by_client.pop(state.client_id, None)


def _claim_recording(ws_id: int, state: RecordingState) -> str | None:
    """Claim a bounded recording slot, returning an error code on refusal."""
    if state.owns_slot:
        _release_recording(ws_id, state)

    client_recordings = active_recordings_by_client.get(state.client_id, set())
    if len(client_recordings) >= MAX_CONCURRENT_RECORDINGS_PER_CLIENT:
        return "client_recording_limit"
    if len(active_recording_ids) >= MAX_CONCURRENT_RECORDINGS:
        return "server_recording_limit"

    state.audio = bytearray()
    state.started_at = time.monotonic()
    state.owns_slot = True
    active_recording_ids.add(ws_id)
    active_recordings_by_client.setdefault(state.client_id, set()).add(ws_id)
    return None


def _recording_expired(state: RecordingState) -> bool:
    return bool(
        state.started_at is not None
        and time.monotonic() - state.started_at >= MAX_RECORDING_SECONDS
    )


async def _send_voice_error(websocket: WebSocket, code: str, message: str) -> None:
    await manager.send_personal_message(
        {"type": MSG_TYPE_ERROR, "code": code, "message": message}, websocket
    )


def _write_wav(path: str, audio: bytearray) -> None:
    """Write raw PCM audio bytes to a WAV file."""
    with wave.open(path, "wb") as wf:
        wf.setnchannels(WAV_CHANNELS)
        wf.setsampwidth(WAV_SAMPLE_WIDTH)
        wf.setframerate(WAV_FRAME_RATE)
        wf.writeframes(audio)


async def _transcribe_audio(audio: bytearray) -> str | None:
    """Write audio to a temp WAV file, transcribe it, clean up, and return transcript."""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        try:
            await asyncio.to_thread(_write_wav, tmp_path, audio)
        finally:
            # Once PCM is persisted to the bounded temporary WAV, the in-memory
            # recording buffer is no longer needed while STT runs.
            audio.clear()
        transcript = await asyncio.to_thread(stt_service.transcribe, tmp_path)
        return transcript
    finally:
        if os.path.exists(tmp_path):
            await asyncio.to_thread(os.unlink, tmp_path)


async def _run_ai_completion(
    transcript: str, app: str, user_id: str
) -> str:
    """Run AI completion for a voice transcript and return the response text."""
    system_prompt = VOICE_SYSTEM_PROMPTS.get(app, VOICE_SYSTEM_PROMPTS["default"])
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": transcript},
    ]

    try:
        voice_model, voice_temp = await _resolve_voice_agent()
        result = await complete_with_memory(
            messages=messages,
            model=voice_model,
            project_id=f"voice-{app}",
            source=CompletionSource.VOICE,
            use_memory=True,
            store_as_episode=True,
            memory_group_id=user_id,
            max_tokens=None,
            temperature=voice_temp,
        )
        logger.info(
            "Voice completion for %s: memory_facts=%s, episode=%s",
            user_id,
            result.memory_facts_injected,
            result.episode_uuid,
        )
        return result.content
    except Exception as exc:
        logger.error("Completion error for %s: %s", user_id, type(exc).__name__)
        return FALLBACK_RESPONSE


async def _handle_stop(
    websocket: WebSocket,
    ws_id: int,
    state: RecordingState,
    user_id: str,
    app: str,
    mode: str,
) -> None:
    """Process buffered audio on recording stop: transcribe then optionally run AI."""
    # Transfer buffer ownership to this stack frame before any await. Keep the
    # concurrency slot until STT/completion finishes so rapid stop/start cycles
    # cannot create an unbounded queue of inference work.
    full_audio = state.audio
    state.audio = bytearray()
    state.started_at = None
    if not full_audio:
        _release_recording(ws_id, state)
        return

    logger.info("Stopped recording for %s; processing %d PCM bytes", user_id, len(full_audio))

    try:
        try:
            transcript = await _transcribe_audio(full_audio)
        except Exception as exc:
            logger.error("STT error for %s: %s", user_id, type(exc).__name__)
            await _send_voice_error(websocket, "transcription_failed", "Audio transcription failed")
            return

        if not transcript:
            logger.warning("No transcript generated for %s", user_id)
            return

        # Transcript content is intentionally never written to server logs.
        logger.info("Transcript generated for %s (%s): %d chars", user_id, app, len(transcript))
        await manager.send_personal_message(
            {"type": MSG_TYPE_TRANSCRIPT, "data": transcript}, websocket
        )

        if mode != MODE_TRANSCRIBE:
            response_text = await _run_ai_completion(transcript, app, user_id)
            await manager.send_personal_message(
                {"type": MSG_TYPE_RESPONSE, "data": response_text}, websocket
            )
    finally:
        # Drop the local allocation on success, failure, or cancelled sends.
        full_audio.clear()
        _release_recording(ws_id, state)


async def _handle_message(
    websocket: WebSocket,
    ws_id: int,
    state: RecordingState,
    user_id: str,
    app: str,
    mode: str,
    data: str,
) -> None:
    """Parse and dispatch a single WebSocket message."""
    try:
        message = json.loads(data)
    except json.JSONDecodeError:
        logger.warning("Invalid JSON received from voice client %s", user_id)
        await _send_voice_error(websocket, "invalid_message", "Message must be valid JSON")
        return

    if not isinstance(message, dict):
        await _send_voice_error(websocket, "invalid_message", "Message must be a JSON object")
        return

    msg_type = message.get("type")

    if msg_type == MSG_TYPE_AUDIO:
        if not state.is_recording:
            await _send_voice_error(websocket, "recording_not_started", "Start recording first")
            return
        if _recording_expired(state):
            _release_recording(ws_id, state)
            await _send_voice_error(
                websocket,
                "recording_too_long",
                f"Recording exceeds the {MAX_RECORDING_SECONDS:g}-second limit",
            )
            return

        encoded_audio = message.get("data")
        if not isinstance(encoded_audio, str):
            _release_recording(ws_id, state)
            await _send_voice_error(websocket, "invalid_audio", "Audio data must be base64 text")
            return

        remaining_bytes = MAX_RECORDING_BYTES - len(state.audio)
        max_encoded_length = 4 * ((remaining_bytes + 2) // 3)
        if len(encoded_audio) > max_encoded_length:
            _release_recording(ws_id, state)
            await _send_voice_error(
                websocket,
                "recording_too_large",
                f"Recording exceeds the {MAX_RECORDING_BYTES}-byte PCM limit",
            )
            return

        try:
            audio_data = base64.b64decode(encoded_audio, validate=True)
        except (binascii.Error, ValueError):
            _release_recording(ws_id, state)
            await _send_voice_error(websocket, "invalid_audio", "Audio data is not valid base64")
            return

        if len(audio_data) > remaining_bytes:
            _release_recording(ws_id, state)
            await _send_voice_error(
                websocket,
                "recording_too_large",
                f"Recording exceeds the {MAX_RECORDING_BYTES}-byte PCM limit",
            )
            return
        state.audio.extend(audio_data)

    elif msg_type == MSG_TYPE_CONTROL:
        action = message.get("action")
        if action == ACTION_START:
            error_code = _claim_recording(ws_id, state)
            if error_code:
                await _send_voice_error(
                    websocket,
                    error_code,
                    "Another recording already owns the available recording slot",
                )
                return
            logger.info("Started recording for %s", user_id)
        elif action == ACTION_STOP:
            await _handle_stop(websocket, ws_id, state, user_id, app, mode)

    elif msg_type == MSG_TYPE_TEXT:
        text_data = message.get("data")
        text_length = len(text_data) if isinstance(text_data, str) else 0
        logger.info("Received text metadata from %s: %d chars", user_id, text_length)


async def _receive_voice_message(
    websocket: WebSocket, ws_id: int, state: RecordingState
) -> str | None:
    """Receive one message while enforcing wall-clock recording duration."""
    if state.started_at is None:
        return await websocket.receive_text()

    remaining = MAX_RECORDING_SECONDS - (time.monotonic() - state.started_at)
    if remaining <= 0:
        _release_recording(ws_id, state)
        await _send_voice_error(
            websocket,
            "recording_too_long",
            f"Recording exceeds the {MAX_RECORDING_SECONDS:g}-second limit",
        )
        return None

    try:
        return await asyncio.wait_for(websocket.receive_text(), timeout=remaining)
    except TimeoutError:
        _release_recording(ws_id, state)
        await _send_voice_error(
            websocket,
            "recording_too_long",
            f"Recording exceeds the {MAX_RECORDING_SECONDS:g}-second limit",
        )
        return None


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    user_id: str = Query(..., description="User ID"),
    app: str = Query(..., description="Application name (summitflow/portfolio)"),
    session_id: str = Query(None, description="Optional Session ID"),
    mode: str = Query("assistant", description="Mode: 'assistant' (full) or 'transcribe' (transcript only)"),
) -> None:
    ws_id = id(websocket)
    state = RecordingState(client_id=user_id)
    recording_states[ws_id] = state
    connected = False

    try:
        await manager.connect(websocket, user_id, session_id)
        connected = True
        while True:
            data = await _receive_voice_message(websocket, ws_id, state)
            if data is not None:
                await _handle_message(websocket, ws_id, state, user_id, app, mode, data)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        # Do not log message bodies, transcripts, or exception text that could
        # contain them. The exception class is sufficient for diagnostics.
        logger.error("Voice WebSocket failed for %s: %s", user_id, type(exc).__name__)
    finally:
        _release_recording(ws_id, state)
        recording_states.pop(ws_id, None)
        if connected:
            manager.disconnect(websocket, user_id, session_id)


async def _resolve_voice_agent() -> tuple[str, float]:
    """Resolve model and temperature from the voice-responder agent config."""
    try:
        from app.db import _get_session_factory
        from app.services.agent_model_router import RoutingContext
        from app.services.agent_routing_utils import resolve_agent

        session_factory = _get_session_factory()
        async with session_factory() as db:
            resolved = await resolve_agent(
                "voice-responder",
                db,
                RoutingContext(requires_audio=True),
            )
            return resolved.model, resolved.agent.temperature
    except Exception as exc:
        raise RuntimeError("Failed to resolve voice-responder agent") from exc

    raise RuntimeError("voice-responder agent not found")
