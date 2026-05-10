"""
SQLAlchemy models for Agent Hub.

Tables:
- sessions: AI conversation sessions
- session_events: Full session event timeline (messages, tool calls, etc.)
- credentials: Encrypted API credentials
- cost_logs: Token usage and cost tracking
- models/model_aliases: DB-backed LLM model catalog and aliases
"""

from __future__ import annotations

from .adaptive_routing import (
    AgentRoutingProfile,
    AgentWorkloadRoutingMode,
    CapabilityDimension,
    ManualModelRoute,
    ModelAvailability,
    ModelCapabilityScore,
    ModelWorkloadPerformance,
    ProviderEntitlement,
    RoutingDecision,
    RoutingPolicyVersion,
    WorkloadProfile,
)
from .agent import Agent, AgentVersion
from .agent_benchmark import (
    AgentBenchmarkAttempt,
    AgentBenchmarkExperiment,
    AgentBenchmarkRun,
    AgentRegressionCluster,
)
from .agent_performance_log import AgentPerformanceLog
from .base import Base
from .client import APIKey, Client, ClientControl
from .compactness_policy import CompactnessPolicy
from .config import Credential, WebhookSubscription
from .feedback import FeedbackItem, FeedbackVote
from .memory import MemoryInjectionMetric, MemorySettings, UsageStatLog
from .memory_unified import Memory, MemoryReviewRun, MemoryRevision
from .model_catalog import ModelAlias, ModelCatalogEntry
from .model_catalog_sync_state import ModelCatalogSyncState
from .model_enrichment import ModelEnrichment
from .narration_tag import NarrationTag
from .persona import Persona
from .persona_scheduled_job import PersonaScheduledJob
from .project_permission import ProjectPermission
from .prompt import AgentPrompt, Prompt, PromptRevision
from .push_subscription import PushSubscription
from .runtime_context import RuntimeContextOverride
from .session import (
    CostLog,
    Session,
    SessionEvent,
    SessionEventType,
    SessionSummarySegment,
)
from .telemetry import RequestLog, TruncationEvent
from .work_chat import ActionRequest, SessionBinding
from .workflow_schedule_control import WorkflowScheduleControl

# Export all models for backward compatibility
__all__ = [
    "APIKey",
    "ActionRequest",
    "Agent",
    "AgentBenchmarkAttempt",
    "AgentBenchmarkExperiment",
    "AgentBenchmarkRun",
    "AgentPerformanceLog",
    "AgentPrompt",
    "AgentRegressionCluster",
    "AgentRoutingProfile",
    "AgentVersion",
    "AgentWorkloadRoutingMode",
    "Base",
    "CapabilityDimension",
    "Client",
    "ClientControl",
    "CompactnessPolicy",
    "CostLog",
    "Credential",
    "FeedbackItem",
    "FeedbackVote",
    "ManualModelRoute",
    "Memory",
    "MemoryInjectionMetric",
    "MemoryReviewRun",
    "MemoryRevision",
    "MemorySettings",
    "ModelAlias",
    "ModelAvailability",
    "ModelCapabilityScore",
    "ModelCatalogEntry",
    "ModelCatalogSyncState",
    "ModelEnrichment",
    "ModelWorkloadPerformance",
    "NarrationTag",
    "Persona",
    "PersonaScheduledJob",
    "ProjectPermission",
    "Prompt",
    "PromptRevision",
    "ProviderEntitlement",
    "PushSubscription",
    "RequestLog",
    "RoutingDecision",
    "RoutingPolicyVersion",
    "RuntimeContextOverride",
    "Session",
    "SessionBinding",
    "SessionEvent",
    "SessionEventType",
    "SessionSummarySegment",
    "TruncationEvent",
    "UsageStatLog",
    "WebhookSubscription",
    "WorkflowScheduleControl",
    "WorkloadProfile",
]
