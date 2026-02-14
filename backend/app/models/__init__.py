"""
SQLAlchemy models for Agent Hub.

Tables:
- sessions: AI conversation sessions
- messages: Individual messages within sessions
- credentials: Encrypted API credentials
- cost_logs: Token usage and cost tracking
- llm_models: LLM model registry (centralized model definitions)
"""

from __future__ import annotations

# Import all models for easy access
from .agent import Agent, AgentVersion

# Import Base first
from .base import Base
from .client import APIKey, Client, ClientControl
from .config import Credential, WebhookSubscription
from .memory import MemoryInjectionMetric, MemorySettings, UsageStatLog
from .prompt import AgentPrompt, Prompt
from .session import (
    CostLog,
    Message,
    Session,
    SessionEvent,
    SessionEventType,
    SessionSummarySegment,
)
from .telemetry import RequestLog, TruncationEvent

# Export all models for backward compatibility
__all__ = [
    "APIKey",
    "Agent",
    "AgentPrompt",
    "AgentVersion",
    "Base",
    "Client",
    "ClientControl",
    "CostLog",
    "Credential",
    "MemoryInjectionMetric",
    "MemorySettings",
    "Message",
    "Prompt",
    "RequestLog",
    "Session",
    "SessionEvent",
    "SessionEventType",
    "SessionSummarySegment",
    "TruncationEvent",
    "UsageStatLog",
    "WebhookSubscription",
]
