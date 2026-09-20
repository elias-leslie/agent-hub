"""HTTP helpers for the complete command."""

from __future__ import annotations

import base64
import mimetypes
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import typer
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


def handle_error_response(response: httpx.Response) -> None:
    """Handle a non-2xx response, printing diagnostics and exiting."""
    try:
        detail = response.json().get("detail", response.text)
    except Exception:
        detail = response.text
    if not isinstance(detail, dict):
        output_error(f"API error ({response.status_code}): {detail}")
        raise typer.Exit(1) from None
    output_error(detail.get("message", str(detail)))
    agents = detail.get("available_agents", [])
    if agents:
        print("\nAvailable agents:", file=sys.stderr)
        for info in agents:
            print(f"  {info}", file=sys.stderr)
    raise typer.Exit(1) from None


def build_headers(
    client_id: str,
    request_source: str,
    source_client: str,
    skip_cache: bool,
    tool_name: str = "st complete",
) -> dict[str, str]:
    """Build request headers for /api/complete."""
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "X-Client-Id": client_id,
        "X-Request-Source": request_source,
        "X-Source-Client": source_client,
        "X-Tool-Name": tool_name,
    }
    if skip_cache:
        headers["X-Skip-Cache"] = "true"
    return headers


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


def build_payload(
    message: str, project_id: str, agent_slug: str | None,
    memory_group_id: str | None, working_dir: str | None,
    session_id: str | None, thinking_level: str | None,
    trace_id: str | None, use_memory: bool, execute_tools: bool,
    task_type: str | None,
    max_turns: int | None, stream: bool, include_roles: list[str] | None,
    images: list[str] | None = None,
    *,
    audios: list[str] | None = None,
    parent_session_id: str | None = None,
    source_metadata: dict[str, Any] | None = None,
    work_context: dict[str, Any] | None = None,
    read_only: bool = False,
    adhoc: bool = False,
    adhoc_spec: dict[str, Any] | None = None,
    routing_exclude_providers: list[str] | None = None,
    routing_cost_preference: str | None = None,
) -> dict[str, Any]:
    """Build request payload for /api/complete."""
    content: str | list[dict[str, Any]]
    if images or audios:
        content = [encode_image(img) for img in images or []]
        content.extend(encode_audio(audio) for audio in audios or [])
        content.append({"type": "text", "text": message})
    else:
        content = message
    payload: dict[str, Any] = {
        "project_id": project_id,
        "messages": [{"role": "user", "content": content}],
    }
    for key, val in [
        ("agent_slug", agent_slug), ("memory_group_id", memory_group_id),
        ("working_dir", working_dir), ("session_id", session_id),
        ("thinking_level", thinking_level), ("trace_id", trace_id),
        ("task_type", task_type), ("parent_session_id", parent_session_id),
    ]:
        if val:
            payload[key] = val
    payload["use_memory"] = use_memory
    if execute_tools:
        payload["execute_tools"] = True
    if max_turns and max_turns > 1:
        payload["max_turns"] = max_turns
    if read_only:
        payload["read_only"] = True
    if adhoc:
        payload["adhoc"] = True
    if adhoc_spec:
        payload["adhoc_spec"] = adhoc_spec
    if routing_exclude_providers:
        payload["routing_exclude_providers"] = routing_exclude_providers
    if routing_cost_preference:
        payload["routing_cost_preference"] = routing_cost_preference
    if stream:
        payload["stream"] = True
    if include_roles:
        payload["include_roles"] = include_roles
    if source_metadata:
        payload["source_metadata"] = source_metadata
    if work_context:
        payload["work_context"] = work_context
    return payload


def stream_complete(
    agent_hub_url: str, headers: dict[str, str],
    payload: dict[str, Any], timeout: float | None,
) -> dict[str, Any]:
    """Stream SSE completion, printing content chunks as they arrive."""
    import json

    content_parts: list[str] = []
    last_data: dict[str, Any] = {}
    from ._api_paths import COMPLETE_PATH

    url = f"{agent_hub_url}{COMPLETE_PATH}"
    http_timeout = httpx.Timeout(connect=5.0, read=timeout, write=30.0, pool=30.0)
    with httpx.Client(timeout=http_timeout) as client, client.stream("POST", url, json=payload, headers=headers) as response:
        if response.status_code >= 400:
            response.read()
            handle_error_response(response)
        for line in response.iter_lines():
            if not line.startswith("data: "):
                continue
            raw = line[6:]
            if raw == "[DONE]":
                break
            try:
                chunk = json.loads(raw)
            except json.JSONDecodeError:
                continue
            last_data = chunk
            text = chunk.get("content", "")
            if text:
                content_parts.append(text)
                sys.stdout.write(text)
                sys.stdout.flush()
    if content_parts:
        sys.stdout.write("\n")
        sys.stdout.flush()
    last_data["content"] = "".join(content_parts)
    return last_data


def _post_with_retry(
    url: str, headers: dict[str, str], payload: dict[str, Any],
    read_timeout: float | None, max_attempts: int = 2,
) -> dict[str, Any]:
    """POST to *url* with simple retry on transient connect errors."""
    from typing import cast

    http_timeout = httpx.Timeout(connect=5.0, read=read_timeout, write=30.0, pool=30.0)
    for attempt in range(1, max_attempts + 1):
        try:
            with httpx.Client(timeout=http_timeout) as client:
                response = client.post(url, json=payload, headers=headers)
            if response.status_code >= 400:
                handle_error_response(response)
            return cast(dict[str, Any], response.json())
        except httpx.ConnectError as e:
            if attempt < max_attempts:
                time.sleep(0.5 * attempt)
                continue
            raise_connect_error("Agent Hub", url, e)
        except httpx.TimeoutException as e:
            raise_timeout_error("Agent Hub", url, read_timeout if read_timeout is not None else 0.0, e)
        except typer.Exit:
            raise
        except Exception as e:
            output_error(f"Request failed: {e}")
            raise typer.Exit(1) from None
    raise AssertionError("unreachable")  # all loop iterations exit via return or raise


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
    adhoc: bool = False,
    adhoc_spec: dict[str, Any] | None = None,
    routing_exclude_providers: list[str] | None = None,
    routing_cost_preference: str | None = None,
    tool_name: str = "st complete",
    audios: list[str] | None = None,
) -> dict[str, Any]:
    """Call /api/complete endpoint."""
    client_id, request_source = load_credentials(default_source="st-complete")
    agent_hub_url = get_agent_hub_url()
    headers = build_headers(client_id, request_source, source_client, skip_cache, tool_name)
    payload = build_payload(
        message, project_id, agent_slug, memory_group_id, working_dir,
        session_id, thinking_level, trace_id, use_memory, execute_tools, task_type,
        max_turns, stream, include_roles, images,
        audios=audios,
        parent_session_id=parent_session_id,
        source_metadata=source_metadata,
        work_context=work_context,
        read_only=read_only,
        adhoc=adhoc,
        adhoc_spec=adhoc_spec,
        routing_exclude_providers=routing_exclude_providers,
        routing_cost_preference=routing_cost_preference,
    )
    read_timeout = timeout
    timeout_for_errors = read_timeout if read_timeout is not None else 30.0
    if stream:
        try:
            return stream_complete(agent_hub_url, headers, payload, read_timeout)
        except httpx.ConnectError as e:
            raise_connect_error("Agent Hub", agent_hub_url, e)
        except httpx.TimeoutException as e:
            raise_timeout_error("Agent Hub", agent_hub_url, timeout_for_errors, e)
    from ._api_paths import COMPLETE_PATH

    return _post_with_retry(f"{agent_hub_url}{COMPLETE_PATH}", headers, payload, read_timeout)
