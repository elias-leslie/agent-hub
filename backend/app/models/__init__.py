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

from .agent import Agent, AgentVersion
from .agent_performance_log import AgentPerformanceLog
from .automation import (
    AutomationDefinition,
    AutomationProfile,
    AutomationProfileRevision,
    AutomationProjectPolicy,
    AutomationRun,
)
from .base import Base
from .client import APIKey, Client
from .config import Credential
from .context_governance import (
    ContextJudgment,
    ContextMaintenanceAttention,
    ContextMaintenanceItem,
    ContextRecord,
)
from .memory import MemoryInjectionMetric, MemorySettings, UsageStatLog
from .memory_unified import Memory, MemoryReviewRun, MemoryRevision
from .model_catalog import ModelAlias, ModelCatalogEntry
from .model_catalog_sync_state import ModelCatalogSyncState
from .model_enrichment import ModelEnrichment
from .narration_tag import NarrationTag
from .native_observation import (
    NativeCommandEntity,
    NativeObservationIssue,
    NativeObservationReceipt,
    NativeObservationSource,
    NativeProjectionState,
    NativeProtocolProfile,
    NativeUserIdentity,
)
from .project_permission import ProjectPermission
from .prompt import AgentPrompt, Prompt, PromptRevision
from .runtime_context import RuntimeContextOverride
from .session import (
    CostLog,
    NativeContinuationTurn,
    Session,
    SessionEvent,
    SessionEventType,
    SessionSummarySegment,
)
from .session_close_settings import SessionCloseSettings
from .subscription_accounting import (
    CreditLot,
    SubscriptionPlan,
    SubscriptionUsageCursor,
    SubscriptionUsageDaily,
    SubscriptionUsageSnapshot,
    UsageCall,
    UsageSession,
)
from .telemetry import RequestLog, TruncationEvent
from .work_chat import SessionBinding
from .workflow_schedule_control import WorkflowScheduleControl

# Export all models for backward compatibility
__all__ = [
    "APIKey",
    "Agent",
    "AgentPerformanceLog",
    "AgentPrompt",
    "AgentVersion",
    "AutomationDefinition",
    "AutomationProfile",
    "AutomationProfileRevision",
    "AutomationProjectPolicy",
    "AutomationRun",
    "Base",
    "Client",
    "CompactnessPolicy",
    "ContextJudgment",
    "ContextMaintenanceAttention",
    "ContextMaintenanceItem",
    "ContextRecord",
    "CostLog",
    "Credential",
    "CreditLot",
    "Memory",
    "MemoryInjectionMetric",
    "MemoryReviewRun",
    "MemoryRevision",
    "MemorySettings",
    "ModelAlias",
    "ModelCatalogEntry",
    "ModelCatalogSyncState",
    "ModelEnrichment",
    "NarrationTag",
    "NativeCommandEntity",
    "NativeContinuationTurn",
    "NativeObservationIssue",
    "NativeObservationReceipt",
    "NativeObservationSource",
    "NativeProjectionState",
    "NativeProtocolProfile",
    "NativeUserIdentity",
    "ProjectPermission",
    "Prompt",
    "PromptRevision",
    "RequestLog",
    "RuntimeContextOverride",
    "Session",
    "SessionBinding",
    "SessionCloseSettings",
    "SessionEvent",
    "SessionEventType",
    "SessionSummarySegment",
    "SubscriptionPlan",
    "SubscriptionUsageCursor",
    "SubscriptionUsageDaily",
    "SubscriptionUsageSnapshot",
    "TruncationEvent",
    "UsageCall",
    "UsageSession",
    "UsageStatLog",
    "WorkflowScheduleControl",
]
