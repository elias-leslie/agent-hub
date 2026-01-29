"""
Example webhook handler for memory system integration.

This module demonstrates how an external memory system can:
1. Register a webhook to receive session events
2. Verify webhook signatures for security
3. Process memory-relevant events (MESSAGE, TOOL_USE)

Usage:
    # Register webhook with Agent Hub
    POST /api/webhooks
    {
        "url": "https://memory-system.example.com/webhook",
        "event_types": ["message", "tool_use", "complete"],
        "project_id": null,  # or specific project
        "description": "Memory system integration"
    }

    # Response includes secret (store securely!)
    {
        "id": 1,
        "secret": "abc123...",  # 64 hex chars, only shown once
        ...
    }

    # Memory system receives POSTs with:
    # Headers:
    #   X-Webhook-Signature: <HMAC-SHA256 signature>
    #   X-Webhook-Id: <webhook ID>
    # Body:
    #   {"event_type": "...", "session_id": "...", "timestamp": "...", "data": {...}}
"""

import hashlib
import hmac
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class MemoryExtractionResult:
    """Result of extracting memories from an event."""

    session_id: str
    timestamp: datetime
    content_type: str  # "message" | "tool_pattern" | "error"
    content: str
    metadata: dict[str, Any]


def verify_webhook_signature(payload: bytes, signature: str, secret: str) -> bool:
    """
    Verify the HMAC-SHA256 signature from Agent Hub webhook.

    Args:
        payload: Raw request body bytes.
        signature: Value of X-Webhook-Signature header.
        secret: Webhook secret from registration.

    Returns:
        True if signature is valid.

    Example:
        @app.post("/webhook")
        async def handle_webhook(request: Request):
            body = await request.body()
            signature = request.headers.get("X-Webhook-Signature", "")
            if not verify_webhook_signature(body, signature, WEBHOOK_SECRET):
                raise HTTPException(401, "Invalid signature")
            # Process event...
    """
    expected = hmac.new(
        secret.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def extract_memory_from_message(event_data: dict[str, Any]) -> MemoryExtractionResult | None:
    """
    Extract memory-relevant content from a MESSAGE event.

    Memory systems typically want to capture:
    - User questions and context
    - Assistant responses and explanations
    - System prompts (for understanding behavior)

    Args:
        event_data: The "data" field from a MESSAGE event.

    Returns:
        MemoryExtractionResult or None if not memory-relevant.
    """
    role = event_data.get("role", "")
    content = event_data.get("content", "")

    if not content or len(content) < 10:
        return None

    return MemoryExtractionResult(
        session_id="",  # Set by caller
        timestamp=datetime.now(UTC),  # Set by caller
        content_type="message",
        content=content,
        metadata={
            "role": role,
            "tokens": event_data.get("tokens"),
        },
    )


def extract_pattern_from_tool_use(event_data: dict[str, Any]) -> MemoryExtractionResult | None:
    """
    Extract operational patterns from a TOOL_USE event.

    Memory systems can learn from tool usage patterns:
    - Which tools are used together
    - Common input patterns
    - Success/failure rates

    Args:
        event_data: The "data" field from a TOOL_USE event.

    Returns:
        MemoryExtractionResult or None if not pattern-relevant.
    """
    tool_name = event_data.get("tool_name", "")
    tool_input = event_data.get("tool_input", {})

    if not tool_name:
        return None

    # Summarize tool usage as a pattern
    pattern = f"Used {tool_name}"
    if tool_input:
        # Extract key patterns without sensitive data
        keys = list(tool_input.keys())[:5]
        if keys:
            pattern += f" with {', '.join(keys)}"

    return MemoryExtractionResult(
        session_id="",
        timestamp=datetime.now(UTC),
        content_type="tool_pattern",
        content=pattern,
        metadata={
            "tool_name": tool_name,
            "input_keys": list(tool_input.keys()),
            "has_output": event_data.get("tool_output") is not None,
        },
    )


class MemoryWebhookHandler:
    """
    Example handler for processing Agent Hub webhooks.

    This demonstrates a pattern that memory systems can adapt.
    """

    def __init__(self, secret: str):
        """
        Initialize handler with webhook secret.

        Args:
            secret: The secret returned when registering the webhook.
        """
        self.secret = secret
        self._pending_memories: list[MemoryExtractionResult] = []

    def verify_and_parse(self, payload: bytes, signature: str) -> dict[str, Any] | None:
        """
        Verify signature and parse webhook payload.

        Args:
            payload: Raw request body.
            signature: X-Webhook-Signature header value.

        Returns:
            Parsed event dict or None if verification fails.
        """
        if not verify_webhook_signature(payload, signature, self.secret):
            logger.warning("Webhook signature verification failed")
            return None

        try:
            result: dict[str, Any] = json.loads(payload)
            return result
        except json.JSONDecodeError:
            logger.error("Failed to parse webhook payload")
            return None

    def process_event(self, event: dict[str, Any]) -> list[MemoryExtractionResult]:
        """
        Process a verified webhook event.

        Args:
            event: Parsed event dict.

        Returns:
            List of extracted memories (may be empty).
        """
        event_type = event.get("event_type")
        session_id = event.get("session_id", "")
        timestamp_str = event.get("timestamp", "")
        data = event.get("data", {})

        try:
            timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            timestamp = datetime.now(UTC)

        results = []

        if event_type == "message":
            memory = extract_memory_from_message(data)
            if memory:
                memory.session_id = session_id
                memory.timestamp = timestamp
                results.append(memory)

        elif event_type == "tool_use":
            pattern = extract_pattern_from_tool_use(data)
            if pattern:
                pattern.session_id = session_id
                pattern.timestamp = timestamp
                results.append(pattern)

        elif event_type == "complete":
            # Session complete - trigger batch processing
            logger.info(
                f"Session {session_id} complete: "
                f"{data.get('input_tokens', 0)} in, "
                f"{data.get('output_tokens', 0)} out"
            )

        elif event_type == "error":
            # Log errors for debugging
            logger.warning(
                f"Session {session_id} error: {data.get('error_type')}: {data.get('error_message')}"
            )

        return results


# Example FastAPI integration:
#
# from fastapi import FastAPI, Request, HTTPException
#
# app = FastAPI()
# handler = MemoryWebhookHandler(secret=os.environ["WEBHOOK_SECRET"])
#
# @app.post("/webhook")
# async def receive_webhook(request: Request):
#     body = await request.body()
#     signature = request.headers.get("X-Webhook-Signature", "")
#
#     event = handler.verify_and_parse(body, signature)
#     if event is None:
#         raise HTTPException(401, "Invalid signature or payload")
#
#     memories = handler.process_event(event)
#     for memory in memories:
#         await store_memory(memory)  # Your storage logic
#
#     return {"status": "ok", "memories_extracted": len(memories)}
