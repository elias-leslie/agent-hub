import type { CatalogModel } from '@/lib/models'

export type {
  AgentPreview,
  AgentPreviewMemoryDebug,
  AgentPreviewMemoryPlanEntry,
  AgentPreviewSection,
  PreviewProjectOption,
  PreviewScenario,
  PreviewTaskType,
} from '@/types/agent-preview'

import type { MemoryConfig } from './components/memory/types'

export interface CommitteeSeatConfig {
  key: string
  label: string
  enabled: boolean
  agent_slug: string
  model_id: string | null
  instruction: string | null
  weight: number
}

export interface CommitteeOrchestratorConfig {
  agent_slug: string
  model_id: string | null
  instruction: string | null
}

export interface CommitteeConfig {
  orchestrator: CommitteeOrchestratorConfig
  seats: CommitteeSeatConfig[]
}

export interface Agent {
  id: number
  slug: string
  name: string
  description: string | null
  system_prompt: string
  primary_model_id: string
  fallback_models: string[]
  escalation_model_id: string | null
  strategies: Record<string, unknown> & { committee?: CommitteeConfig }
  temperature: number
  thinking_level: string | null
  verbosity_level: string | null
  is_active: boolean
  is_coding_agent: boolean
  memory_config: (MemoryConfig & Record<string, unknown>) | null
  effective_memory_config: MemoryConfig & Record<string, unknown>
  max_concurrency: number | null
  max_subagent_concurrency: number | null
  daily_token_budget: number | null
  hourly_request_limit: number | null
  timeout_seconds: number | null
  version: number
  created_at: string
  updated_at: string
}

export type ModelInfo = CatalogModel

export type RoutingMode =
  | 'manual_locked'
  | 'auto_shadow'
  | 'auto_canary'
  | 'auto'

export type RoutingRiskTier = 'low' | 'normal' | 'elevated' | 'critical'

export interface ManualRoute {
  id: number
  workload_profile: string | null
  primary_model_id: string
  fallback_models: string[]
  escalation_model_id: string | null
  reason: string | null
  owner: string | null
  expires_at: string | null
  allow_health_fallback: boolean
  enabled: boolean
}

export interface WorkloadProfileSummary {
  key: string
  label: string
  risk_tier: RoutingRiskTier
  default_routing_mode: RoutingMode
}

export interface WorkloadRoutingOverride {
  workload_profile: string
  routing_mode: RoutingMode
  canary_percent: number
  reason: string | null
  owner: string | null
  enabled: boolean
}

export interface AgentRouting {
  agent_slug: string
  default_routing_mode: RoutingMode
  risk_tier: RoutingRiskTier
  cost_policy: string
  subscription_policy: string
  exploration_policy: string
  quality_floor: number | null
  workload_profiles: WorkloadProfileSummary[]
  workload_overrides: WorkloadRoutingOverride[]
  manual_routes: ManualRoute[]
}

export interface AgentRoutingUpdate {
  default_routing_mode?: RoutingMode
  risk_tier?: RoutingRiskTier
  cost_policy?: string
  subscription_policy?: string
  exploration_policy?: string
  quality_floor?: number | null
}

export interface WorkloadRoutingUpdate {
  routing_mode?: RoutingMode
  canary_percent?: number
  reason?: string | null
  owner?: string | null
  enabled?: boolean
}

export type TabId =
  | 'general'
  | 'models'
  | 'parameters'
  | 'prompts'
  | 'memory'
  | 'committee'
