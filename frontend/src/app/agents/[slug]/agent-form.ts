import { cloneConfig, parseConfig } from './components/memory/utils'
import type { Agent } from './types'

function cloneStrategies(strategies: Agent['strategies']): Agent['strategies'] {
  return JSON.parse(JSON.stringify(strategies ?? {})) as Agent['strategies']
}

export function createAgentFormData(agent: Agent): Partial<Agent> {
  const effectiveMemoryConfig = cloneConfig(agent.effective_memory_config)

  return {
    name: agent.name,
    description: agent.description,
    primary_model_id: agent.primary_model_id,
    fallback_models: agent.fallback_models,
    escalation_model_id: agent.escalation_model_id,
    strategies: cloneStrategies(agent.strategies),
    temperature: agent.temperature,
    thinking_level: agent.thinking_level,
    verbosity_level: agent.verbosity_level,
    is_active: agent.is_active,
    is_coding_agent: agent.is_coding_agent,
    memory_config: agent.memory_config
      ? parseConfig(agent.memory_config, effectiveMemoryConfig)
      : null,
    effective_memory_config: effectiveMemoryConfig,
    max_concurrency: agent.max_concurrency ?? null,
    max_subagent_concurrency: agent.max_subagent_concurrency ?? null,
    daily_token_budget: agent.daily_token_budget ?? null,
    hourly_request_limit: agent.hourly_request_limit ?? null,
  }
}

export function buildAgentUpdatePayload(
  formData: Partial<Agent>,
): Partial<Agent> {
  const payload = { ...formData }

  if (!payload.name) delete payload.name
  if (!payload.primary_model_id) delete payload.primary_model_id
  delete payload.system_prompt
  delete payload.effective_memory_config
  if (payload.memory_config) {
    payload.memory_config = cloneConfig(
      payload.memory_config as NonNullable<Agent['memory_config']>,
    )
  }
  if (payload.strategies) {
    payload.strategies = cloneStrategies(
      payload.strategies as Agent['strategies'],
    )
  }

  return payload
}
