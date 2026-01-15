import logging
from typing import BinaryIO

from faster_whisper import WhisperModel

logger = logging.getLogger("passport.stt")


class STTService:
    def __init__(self, model_size: str = "base", device: str = "cpu", compute_type: str = "int8"):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.model = None
        # Lazy load model

    def load_model(self):
        if not self.model:
            logger.info(f"Loading faster-whisper model: {self.model_size} on {self.device}")
            try:
                self.model = WhisperModel(
                    self.model_size, device=self.device, compute_type=self.compute_type
                )
                logger.info("Model loaded successfully")
            except Exception as e:
                logger.error(f"Failed to load model: {e}")
                raise

    def transcribe(self, audio_file: str | BinaryIO):
        if not self.model:
            self.load_model()

        segments, info = self.model.transcribe(audio_file, beam_size=5)

        logger.debug(
            f"Detected language '{info.language}' with probability {info.language_probability}"
        )

        full_text = ""
        for segment in segments:
            full_text += segment.text + " "

        return full_text.strip()


# Singleton instance
stt_service = STTService()
