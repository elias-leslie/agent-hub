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
from .config import Credential, UserPreferences, WebhookSubscription
from .memory import MemoryInjectionMetric, MemorySettings, UsageStatLog
from .roundtable import RoundtableMessage, RoundtableSession
from .session import CostLog, Message, Session
from .telemetry import RequestLog, TruncationEvent

# Export all models for backward compatibility
__all__ = [
    "APIKey",
    "Agent",
    "AgentVersion",
    "Base",
    "Client",
    "ClientControl",
    "CostLog",
    "Credential",
    "MemoryInjectionMetric",
    "MemorySettings",
    "Message",
    "RequestLog",
    "RoundtableMessage",
    "RoundtableSession",
    "Session",
    "TruncationEvent",
    "UsageStatLog",
    "UserPreferences",
    "WebhookSubscription",
]
