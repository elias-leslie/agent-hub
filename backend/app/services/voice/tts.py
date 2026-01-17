import io
import logging

import edge_tts

logger = logging.getLogger("agent_hub.tts")

# Available voices - using natural-sounding US English voices
VOICES = {
    "default": "en-US-AriaNeural",  # Female, conversational
    "male": "en-US-GuyNeural",  # Male, conversational
    "female": "en-US-JennyNeural",  # Female, friendly
}


class TTSService:
    def __init__(self, voice: str = "default"):
        self.voice = VOICES.get(voice, VOICES["default"])

    async def synthesize(self, text: str, voice: str | None = None) -> bytes:
        """Convert text to speech, returns MP3 audio bytes."""
        voice_id = VOICES.get(voice, self.voice) if voice else self.voice

        logger.info(f"TTS: Synthesizing {len(text)} chars with voice {voice_id}")

        communicate = edge_tts.Communicate(text, voice_id)
        audio_buffer = io.BytesIO()

        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_buffer.write(chunk["data"])

        audio_bytes = audio_buffer.getvalue()
        logger.info(f"TTS: Generated {len(audio_bytes)} bytes of audio")
        return audio_bytes


# Singleton instance
tts_service = TTSService()
