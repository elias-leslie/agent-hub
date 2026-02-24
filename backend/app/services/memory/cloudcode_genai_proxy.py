"""Proxy that mimics genai.Client for graphiti_core, routing through CloudCode OAuth.

CloudCode PA (cloudcode-pa.googleapis.com) only supports generateContent,
not embedContent. So this proxy is used for LLM and reranker clients only.
Embeddings stay on the API key path via the regular genai.Client.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from google.genai import types

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lightweight response wrappers (matches what graphiti_core accesses)
# ---------------------------------------------------------------------------


@dataclass
class _Part:
    text: str = ""


@dataclass
class _Content:
    role: str = "model"
    parts: list[_Part] = field(default_factory=list)


@dataclass
class _Candidate:
    content: _Content = field(default_factory=_Content)
    finish_reason: str = "STOP"


@dataclass
class _UsageMetadata:
    prompt_token_count: int = 0
    candidates_token_count: int = 0
    total_token_count: int = 0


@dataclass
class _GenerateContentResponse:
    candidates: list[_Candidate] = field(default_factory=list)
    usage_metadata: _UsageMetadata = field(default_factory=_UsageMetadata)

    @property
    def text(self) -> str | None:
        if self.candidates and self.candidates[0].content.parts:
            return self.candidates[0].content.parts[0].text
        return None


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _content_to_dict(content: Any) -> dict[str, Any]:
    """Convert a genai types.Content (or dict/str) to a CloudCode-compatible dict."""
    if isinstance(content, dict):
        return content
    if isinstance(content, str):
        return {"role": "user", "parts": [{"text": content}]}
    # types.Content
    parts = []
    for p in getattr(content, "parts", []):
        text = getattr(p, "text", None)
        if text is not None:
            parts.append({"text": text})
    return {"role": getattr(content, "role", "user"), "parts": parts}


# JSON Schema fields that CloudCode doesn't support
_UNSUPPORTED_SCHEMA_KEYS = {
    "$defs",
    "$ref",
    "$schema",
    "$id",
    "const",
    "default",
    "examples",
    "additionalProperties",
    "minLength",
    "maxLength",
    "minimum",
    "maximum",
    "pattern",
    "title",
}


def _clean_schema(schema: Any) -> Any:
    """Recursively strip JSON Schema fields unsupported by CloudCode.

    Resolves $ref/$defs inline where possible, strips the rest.
    """
    if not isinstance(schema, dict):
        return schema

    defs = schema.get("$defs", {})

    def _resolve(node: Any) -> Any:
        if not isinstance(node, dict):
            if isinstance(node, list):
                return [_resolve(item) for item in node]
            return node

        # Resolve $ref
        ref = node.get("$ref")
        if ref and isinstance(ref, str) and ref.startswith("#/$defs/"):
            def_name = ref.split("/")[-1]
            if def_name in defs:
                return _resolve(defs[def_name])
            return {"type": "object"}

        result = {}
        for k, v in node.items():
            if k in _UNSUPPORTED_SCHEMA_KEYS:
                continue
            if k == "properties" and isinstance(v, dict):
                result[k] = {pk: _resolve(pv) for pk, pv in v.items()}
            elif k == "items":
                result[k] = _resolve(v)
            elif k == "anyOf" or k == "oneOf":
                result[k] = [_resolve(item) for item in v]
            else:
                result[k] = v
        return result

    return _resolve(schema)


def _config_to_dict(config: Any) -> tuple[dict[str, Any], str | None]:
    """Extract generation_config dict and system_instruction from a GenerateContentConfig.

    Returns (generation_config_dict, system_instruction_text).
    """
    if config is None:
        return {}, None

    gen_config: dict[str, Any] = {}
    system_instruction: str | None = None

    if isinstance(config, dict):
        return config, None

    # types.GenerateContentConfig
    if hasattr(config, "temperature") and config.temperature is not None:
        gen_config["temperature"] = config.temperature
    if hasattr(config, "max_output_tokens") and config.max_output_tokens is not None:
        gen_config["maxOutputTokens"] = config.max_output_tokens
    if hasattr(config, "response_mime_type") and config.response_mime_type:
        gen_config["responseMimeType"] = config.response_mime_type
    if hasattr(config, "response_schema") and config.response_schema:
        # Pydantic model → JSON schema, cleaned for CloudCode compatibility
        schema = config.response_schema
        if hasattr(schema, "model_json_schema"):
            gen_config["responseSchema"] = _clean_schema(schema.model_json_schema())
    if hasattr(config, "system_instruction") and config.system_instruction:
        si = config.system_instruction
        if isinstance(si, str):
            system_instruction = si
        elif hasattr(si, "text"):
            system_instruction = si.text
        elif hasattr(si, "parts"):
            system_instruction = " ".join(
                getattr(p, "text", str(p)) for p in si.parts
            )

    return gen_config, system_instruction


def _parse_response(raw: dict[str, Any]) -> _GenerateContentResponse:
    """Parse a CloudCode JSON response into a genai-compatible response object."""
    # CloudCode wraps in {"response": {...}}, unwrap if present
    data = raw.get("response", raw)

    candidates = []
    for c in data.get("candidates", []):
        content = c.get("content", {})
        parts = [_Part(text=p.get("text", "")) for p in content.get("parts", [])]
        candidates.append(
            _Candidate(
                content=_Content(role=content.get("role", "model"), parts=parts),
                finish_reason=c.get("finishReason", "STOP"),
            )
        )

    usage = data.get("usageMetadata", {})
    usage_meta = _UsageMetadata(
        prompt_token_count=usage.get("promptTokenCount", 0),
        candidates_token_count=usage.get("candidatesTokenCount", 0),
        total_token_count=usage.get("totalTokenCount", 0),
    )

    return _GenerateContentResponse(candidates=candidates, usage_metadata=usage_meta)


# ---------------------------------------------------------------------------
# Proxy classes (duck-type genai.Client.aio.models)
# ---------------------------------------------------------------------------


class _ModelsProxy:
    """Proxies generate_content calls to CloudCodeClient."""

    def __init__(self, cloudcode_client: Any) -> None:
        self._cc = cloudcode_client

    async def generate_content(
        self,
        *,
        model: str,
        contents: Any,
        config: Any = None,
    ) -> _GenerateContentResponse:
        # Serialize contents
        if isinstance(contents, list):
            cc_contents = [_content_to_dict(c) for c in contents]
        else:
            cc_contents = [_content_to_dict(contents)]

        gen_config, system_instruction = _config_to_dict(config)

        si_dict = None
        if system_instruction:
            si_dict = {"parts": [{"text": system_instruction}]}

        raw = await self._cc.generate_content(
            model=model,
            contents=cc_contents,
            system_instruction=si_dict,
            generation_config=gen_config or None,
        )

        return _parse_response(raw)


class _AioProxy:
    def __init__(self, cloudcode_client: Any) -> None:
        self.models = _ModelsProxy(cloudcode_client)


class CloudCodeGenaiProxy:
    """Drop-in replacement for genai.Client that routes through CloudCode OAuth.

    Only supports generate_content (LLM + reranker).
    Does NOT support embed_content — use a regular genai.Client for embeddings.

    Usage:
        from app.adapters.gemini_cloudcode import CloudCodeClient

        cc = CloudCodeClient(access_token=..., refresh_token=..., project_id=...)
        proxy = CloudCodeGenaiProxy(cc)

        # Pass to graphiti_core:
        llm_client = GeminiClient(config=config, client=proxy)
        reranker = GeminiRerankerClient(config=config, client=proxy)
    """

    def __init__(self, cloudcode_client: Any) -> None:
        self.aio = _AioProxy(cloudcode_client)
