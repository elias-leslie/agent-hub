import base64
import json
import logging
import os
import tempfile
import wave

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.services.voice.connection_manager import manager
from app.services.voice.stt import stt_service

logger = logging.getLogger("agent_hub.api.voice")

router = APIRouter()

# In-memory storage for audio buffers
# { "websocket_id": bytearray() }
audio_buffers = {}


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    user_id: str = Query(..., description="User ID"),
    app: str = Query(..., description="Application name (summitflow/portfolio)"),
    session_id: str = Query(None, description="Optional Session ID"),
):
    await manager.connect(websocket, user_id, session_id)
    ws_id = id(websocket)
    audio_buffers[ws_id] = bytearray()

    try:
        while True:
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
                msg_type = message.get("type")

                if msg_type == "audio":
                    # 1. Decode and Buffer Audio
                    audio_data = base64.b64decode(message["data"])
                    audio_buffers[ws_id].extend(audio_data)

                elif msg_type == "control":
                    action = message.get("action")
                    if action == "start":
                        audio_buffers[ws_id] = bytearray()
                        logger.info(f"Started recording for {user_id}")

                    elif action == "stop":
                        logger.info(f"Stopped recording for {user_id}, processing...")

                        full_audio = audio_buffers[ws_id]
                        if not full_audio:
                            continue

                        # 2. Transcribe
                        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                            tmp_path = tmp.name

                        try:
                            # Write proper WAV file
                            with wave.open(tmp_path, "wb") as wf:
                                wf.setnchannels(1)
                                wf.setsampwidth(2)  # 16-bit
                                wf.setframerate(16000)
                                wf.writeframes(full_audio)

                            transcript = stt_service.transcribe(tmp_path)
                            os.unlink(tmp_path)

                            if transcript:
                                logger.info(f"Transcript for {user_id} ({app}): {transcript}")
                                # Send transcript back to UI
                                await manager.send_personal_message(
                                    {"type": "transcript", "data": transcript}, websocket
                                )

                                # 3. Process with Agent
                                response_text = f"You said: {transcript}. This is the {app} agent."
                                await manager.send_personal_message(
                                    {"type": "response", "data": response_text}, websocket
                                )
                            else:
                                logger.warning(f"No transcript generated for {user_id}")

                        except Exception as e:
                            logger.error(f"STT Error: {e}")
                            if os.path.exists(tmp_path):
                                os.unlink(tmp_path)

                        # Reset buffer
                        audio_buffers[ws_id] = bytearray()

                elif msg_type == "text":
                    logger.info(f"Received text from {user_id}: {message.get('data')}")

            except json.JSONDecodeError:
                logger.error("Invalid JSON received")

    except WebSocketDisconnect:
        manager.disconnect(websocket, user_id, session_id)
        audio_buffers.pop(ws_id, None)
