from __future__ import annotations

from app.llm.model_resolver import resolve_llm_model
from app.llm.provider_support.google_shared import convert_messages
from app.llm.types import AudioContent, Context, UserMessage


def test_google_maps_audio_content_to_inline_data() -> None:
    model = resolve_llm_model("gemini-2.5-flash-lite", "gemini")
    context = Context(
        messages=[
            UserMessage(
                content=[AudioContent(data="UklGRg==", mime_type="audio/wav")],
                timestamp=0,
            )
        ]
    )

    assert convert_messages(model, context) == [
        {
            "role": "user",
            "parts": [
                {
                    "inline_data": {
                        "mime_type": "audio/wav",
                        "data": "UklGRg==",
                    }
                }
            ],
        }
    ]
