import asyncio
import base64
import json
import logging
import os
import tempfile
import wave

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

# Control action constants
ACTION_START = "start"
ACTION_STOP = "stop"

# Mode constants
MODE_TRANSCRIBE = "transcribe"

# WAV audio format constants
WAV_CHANNELS = 1
WAV_SAMPLE_WIDTH = 2  # 16-bit
WAV_FRAME_RATE = 16000

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


# In-memory storage for audio buffers
# { "websocket_id": bytearray() }
audio_buffers = {}


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
        await asyncio.to_thread(_write_wav, tmp_path, audio)
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
            f"Voice completion for {user_id}: "
            f"memory_facts={result.memory_facts_injected}, "
            f"episode={result.episode_uuid}"
        )
        return result.content
    except Exception as e:
        logger.error(f"Completion error for {user_id}: {e}")
        return FALLBACK_RESPONSE


async def _handle_stop(
    websocket: WebSocket, ws_id: int, user_id: str, app: str, mode: str
) -> None:
    """Process buffered audio on recording stop: transcribe then optionally run AI."""
    full_audio = audio_buffers[ws_id]
    if not full_audio:
        return

    logger.info(f"Stopped recording for {user_id}, processing...")

    try:
        transcript = await _transcribe_audio(full_audio)
    except Exception as e:
        logger.error(f"STT Error: {e}")
        audio_buffers[ws_id] = bytearray()
        return

    if not transcript:
        logger.warning(f"No transcript generated for {user_id}")
        audio_buffers[ws_id] = bytearray()
        return

    logger.info(f"Transcript for {user_id} ({app}): {transcript}")
    await manager.send_personal_message(
        {"type": MSG_TYPE_TRANSCRIPT, "data": transcript}, websocket
    )

    if mode != MODE_TRANSCRIBE:
        response_text = await _run_ai_completion(transcript, app, user_id)
        await manager.send_personal_message(
            {"type": MSG_TYPE_RESPONSE, "data": response_text}, websocket
        )

    audio_buffers[ws_id] = bytearray()


async def _handle_message(
    websocket: WebSocket, ws_id: int, user_id: str, app: str, mode: str, data: str
) -> None:
    """Parse and dispatch a single WebSocket message."""
    try:
        message = json.loads(data)
    except json.JSONDecodeError:
        logger.error("Invalid JSON received")
        return

    msg_type = message.get("type")

    if msg_type == MSG_TYPE_AUDIO:
        audio_data = base64.b64decode(message["data"])
        audio_buffers[ws_id].extend(audio_data)

    elif msg_type == MSG_TYPE_CONTROL:
        action = message.get("action")
        if action == ACTION_START:
            audio_buffers[ws_id] = bytearray()
            logger.info(f"Started recording for {user_id}")
        elif action == ACTION_STOP:
            await _handle_stop(websocket, ws_id, user_id, app, mode)

    elif msg_type == MSG_TYPE_TEXT:
        logger.info(f"Received text from {user_id}: {message.get('data')}")


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    user_id: str = Query(..., description="User ID"),
    app: str = Query(..., description="Application name (summitflow/portfolio)"),
    session_id: str = Query(None, description="Optional Session ID"),
    mode: str = Query("assistant", description="Mode: 'assistant' (full) or 'transcribe' (transcript only)"),
) -> None:
    await manager.connect(websocket, user_id, session_id)
    ws_id = id(websocket)
    audio_buffers[ws_id] = bytearray()

    try:
        while True:
            data = await websocket.receive_text()
            await _handle_message(websocket, ws_id, user_id, app, mode, data)
    except WebSocketDisconnect:
        manager.disconnect(websocket, user_id, session_id)
        audio_buffers.pop(ws_id, None)


async def _resolve_voice_agent() -> tuple[str, float]:
    """Resolve model and temperature from the voice-responder agent config."""
    try:
        from app.db import _get_session_factory
        from app.services.adaptive_model_router import RoutingContext
        from app.services.agent_routing_utils import resolve_agent

        session_factory = _get_session_factory()
        async with session_factory() as db:
            resolved = await resolve_agent(
                "voice-responder",
                db,
                RoutingContext(workload_profile="voice_response", requires_audio=True),
            )
            return resolved.model, resolved.agent.temperature
    except Exception as exc:
        raise RuntimeError("Failed to resolve voice-responder agent") from exc

    raise RuntimeError("voice-responder agent not found")
