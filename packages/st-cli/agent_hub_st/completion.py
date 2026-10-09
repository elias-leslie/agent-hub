"""Completion helpers for ST commands, on the canonical agent-hub-client SDK."""

from __future__ import annotations

import base64
import mimetypes
import sys
from pathlib import Path
from typing import Any

import httpx
import typer
from agent_hub import AgentHubClient
from agent_hub.exceptions import AgentHubError
from st_sdk.config import get_agent_hub_url
from st_sdk.credentials import load_credentials
from st_sdk.output import output_error

from ._http_errors import raise_connect_error, raise_timeout_error

_IMAGE_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

_AUDIO_MIME_TYPES = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".aif": "audio/aiff",
    ".aiff": "audio/aiff",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
}


def resolve_message(message: str | None, file: str | None) -> str | None:
    """Resolve a completion message from an argument, file, or piped stdin."""
    if message:
        return message
    if file:
        path = Path(file)
        if not path.is_file():
            output_error(f"File not found: {file}")
            raise typer.Exit(1)
        return path.read_text()
    if not sys.stdin.isatty():
        content = sys.stdin.read()
        if content.strip():
            return content
    return None


def completion_failed(result: dict[str, Any]) -> bool:
    """Return True when Agent Hub encoded a failure in a 200 response."""
    if result.get("error"):
        return True
    content = result.get("content")
    return isinstance(content, str) and content.startswith("Error:")


def encode_image(path: str) -> dict[str, Any]:
    """Read an image file and return an Anthropic-style base64 content block."""
    p = Path(path)
    if not p.is_file():
        output_error(f"Image not found: {path}")
        raise typer.Exit(1)
    suffix = p.suffix.lower()
    media_type = _IMAGE_MIME_TYPES.get(suffix) or mimetypes.guess_type(path)[0] or "image/png"
    data = base64.b64encode(p.read_bytes()).decode()
    return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}}


def encode_audio(path: str) -> dict[str, Any]:
    """Read a supported audio file and return a typed base64 content block."""
    audio_path = Path(path)
    if not audio_path.is_file():
        output_error(f"Audio not found: {path}")
        raise typer.Exit(1)
    media_type = _AUDIO_MIME_TYPES.get(audio_path.suffix.lower())
    if media_type is None:
        supported = ", ".join(sorted(_AUDIO_MIME_TYPES))
        output_error(f"Unsupported audio format: {path}. Supported extensions: {supported}")
        raise typer.Exit(1)
    data = base64.b64encode(audio_path.read_bytes()).decode()
    return {"type": "audio", "source": {"type": "base64", "media_type": media_type, "data": data}}


def build_message(
    message: str, images: list[str] | None = None, audios: list[str] | None = None,
) -> dict[str, Any]:
    """Build the single user message, with image and audio blocks before the text."""
    if not images and not audios:
        return {"role": "user", "content": message}
    content = [encode_image(img) for img in images or []]
    content.extend(encode_audio(audio) for audio in audios or [])
    content.append({"type": "text", "text": message})
    return {"role": "user", "content": content}


def _client(source_client: str, tool_name: str, timeout: float | None) -> AgentHubClient:
    client_id, request_source = load_credentials(default_source="st-complete")
    return AgentHubClient(
        base_url=get_agent_hub_url(), client_name=source_client, client_id=client_id,
        request_source=request_source, timeout=timeout, cli_command=tool_name,
        source_client=source_client,
    )


def _stream(client: AgentHubClient, messages: list[dict[str, Any]], options: dict[str, Any]) -> dict[str, Any]:
    """Print streamed content as it arrives and return the done event plus the full text."""
    parts: list[str] = []
    done: dict[str, Any] = {}
    for chunk in client.stream_sse(messages, **options):
        if chunk.type == "content" and chunk.content:
            parts.append(chunk.content)
            sys.stdout.write(chunk.content)
            sys.stdout.flush()
        elif chunk.type in ("done", "cancelled"):
            done = chunk.model_dump(exclude_none=True, exclude={"content"})
        elif chunk.type == "error":
            done = {"error": chunk.error}
    if parts:
        sys.stdout.write("\n")
        sys.stdout.flush()
    return {**done, "content": "".join(parts)}


def call_complete(
    agent_slug: str | None, message: str, project_id: str = "st-cli",
    source_client: str = "st-cli", use_memory: bool = True,
    memory_group_id: str | None = None, execute_tools: bool = False,
    working_dir: str | None = None, timeout: float | None = None,
    skip_cache: bool = False, session_id: str | None = None,
    thinking_level: str | None = None, max_turns: int | None = None,
    stream: bool = False, trace_id: str | None = None,
    include_roles: list[str] | None = None,
    task_type: str | None = None,
    images: list[str] | None = None,
    parent_session_id: str | None = None,
    source_metadata: dict[str, Any] | None = None,
    work_context: dict[str, Any] | None = None,
    read_only: bool = False,
    tool_name: str = "st complete",
    audios: list[str] | None = None,
) -> dict[str, Any]:
    """Run one Agent Hub completion and return the response as a dict."""
    if not agent_slug:
        output_error("An exact Agent Hub agent slug is required.")
        raise typer.Exit(1)
    messages = [build_message(message, images, audios)]
    options: dict[str, Any] = {
        "project_id": project_id, "agent_slug": agent_slug, "use_memory": use_memory,
        "memory_group_id": memory_group_id, "working_dir": working_dir,
        "execute_tools": execute_tools, "session_id": session_id,
        "thinking_level": thinking_level, "trace_id": trace_id,
        "include_roles": include_roles, "task_type": task_type, "skip_cache": skip_cache,
        "parent_session_id": parent_session_id, "source_metadata": source_metadata,
        "work_context": work_context, "read_only": read_only,
        "max_turns": max_turns if max_turns and max_turns > 1 else 1,
        "timeout_seconds": timeout,
    }
    agent_hub_url = get_agent_hub_url()
    try:
        with _client(source_client, tool_name, timeout) as client:
            if stream:
                return _stream(client, messages, options)
            return client.complete(messages, **options).model_dump(mode="json")
    except httpx.ConnectError as e:
        raise_connect_error("Agent Hub", agent_hub_url, e)
    except httpx.TimeoutException as e:
        raise_timeout_error("Agent Hub", agent_hub_url, timeout if timeout is not None else 0.0, e)
    except AgentHubError as e:
        output_error(str(e))
        raise typer.Exit(1) from None
