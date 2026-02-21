import io
import logging
import time

import edge_tts

logger = logging.getLogger("agent_hub.tts")

# Alias shortcuts for backward compatibility
VOICE_ALIASES = {
    "default": "en-US-AriaNeural",
    "male": "en-US-GuyNeural",
    "female": "en-US-JennyNeural",
}

# Module-level voice list cache (1-hour TTL)
_voices_cache: list[dict] | None = None
_voices_cache_time: float = 0
_VOICES_CACHE_TTL = 3600  # seconds


def _parse_personalities(voice_tag: dict) -> list[str]:
    """Extract personality tags from a VoiceTag dict. Value may be str or list."""
    raw = voice_tag.get("VoicePersonalities", [])
    if isinstance(raw, list):
        return [p.strip() for p in raw if p.strip()]
    if isinstance(raw, str):
        return [p.strip() for p in raw.split(",") if p.strip()]
    return []


async def list_voices(locale_prefix: str = "en") -> list[dict]:
    """List available TTS voices, filtered by locale prefix. Cached for 1 hour."""
    global _voices_cache, _voices_cache_time

    now = time.monotonic()
    if _voices_cache is not None and (now - _voices_cache_time) < _VOICES_CACHE_TTL:
        if locale_prefix:
            return [v for v in _voices_cache if v["locale"].startswith(locale_prefix)]
        return list(_voices_cache)

    voices_manager = await edge_tts.VoicesManager.create()
    all_voices = []
    for v in voices_manager.voices:
        all_voices.append({
            "id": v["ShortName"],
            "name": v["FriendlyName"].replace("Microsoft Server Speech Text to Speech Voice ", "").strip("()"),
            "gender": v.get("Gender", "Unknown"),
            "locale": v["Locale"],
            "personalities": _parse_personalities(v.get("VoiceTag", {})),
        })

    _voices_cache = all_voices
    _voices_cache_time = now
    logger.info(f"Cached {len(all_voices)} TTS voices")

    if locale_prefix:
        return [v for v in all_voices if v["locale"].startswith(locale_prefix)]
    return list(all_voices)


class TTSService:
    def __init__(self, voice: str = "default"):
        self.voice = VOICE_ALIASES.get(voice, VOICE_ALIASES["default"])

    async def synthesize(self, text: str, voice: str | None = None) -> bytes:
        """Convert text to speech, returns MP3 audio bytes."""
        if voice:
            # Support both alias keys ("male") and full IDs ("en-US-GuyNeural")
            voice_id = VOICE_ALIASES.get(voice, voice)
        else:
            voice_id = self.voice

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
