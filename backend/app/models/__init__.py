"""
SQLAlchemy models for Agent Hub.

Tables:
- sessions: AI conversation sessions
- session_events: Full session event timeline (messages, tool calls, etc.)
- credentials: Encrypted API credentials
- cost_logs: Token usage and cost tracking
- llm_models: LLM model registry (centralized model definitions)
"""

from __future__ import annotations

# Import all models for easy access
from .agent import Agent, AgentVersion
from .agent_benchmark import (
    AgentBenchmarkAttempt,
    AgentBenchmarkExperiment,
    AgentBenchmarkRun,
    AgentRegressionCluster,
)
from .agent_performance_log import AgentPerformanceLog

# Import Base first
from .base import Base
from .client import APIKey, Client, ClientControl
from .config import Credential, WebhookSubscription
from .feedback import FeedbackItem, FeedbackVote
from .memory import MemoryInjectionMetric, MemorySettings, UsageStatLog
from .memory_unified import Memory
from .model_enrichment import ModelEnrichment
from .persona import Persona
from .persona_scheduled_job import PersonaScheduledJob
from .project_permission import ProjectPermission
from .prompt import AgentPrompt, Prompt
from .push_subscription import PushSubscription
from .session import (
    CostLog,
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
    "AgentBenchmarkAttempt",
    "AgentBenchmarkExperiment",
    "AgentBenchmarkRun",
    "AgentPerformanceLog",
    "AgentPrompt",
    "AgentRegressionCluster",
    "AgentVersion",
    "Base",
    "Client",
    "ClientControl",
    "CostLog",
    "Credential",
    "FeedbackItem",
    "FeedbackVote",
    "Memory",
    "MemoryInjectionMetric",
    "MemorySettings",
    "ModelEnrichment",
    "Persona",
    "PersonaScheduledJob",
    "ProjectPermission",
    "Prompt",
    "PushSubscription",
    "RequestLog",
    "Session",
    "SessionEvent",
    "SessionEventType",
    "SessionSummarySegment",
    "TruncationEvent",
    "UsageStatLog",
    "WebhookSubscription",
]
