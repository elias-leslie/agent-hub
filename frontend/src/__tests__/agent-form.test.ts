import { describe, expect, it } from 'vitest'
import {
  buildAgentUpdatePayload,
  createAgentFormData,
} from '@/app/agents/[slug]/agent-form'
import type { Agent } from '@/app/agents/[slug]/types'

function makeAgent(overrides: Partial<Agent> = {}): Agent {
  return {
    id: 1,
    slug: 'persona',
    name: 'Persona',
    description: 'Primary persona agent',
    system_prompt: 'You are persona.',
    primary_model_id: 'claude-sonnet-4-6',
    fallback_models: ['gemini-3-flash-preview'],
    escalation_model_id: null,
    strategies: {},
    temperature: 0.7,
    thinking_level: 'medium',
    verbosity_level: 'high',
    is_active: true,
    is_coding_agent: false,
    memory_config: null,
    effective_memory_config: {
      injection_enabled: true,
      project_index_enabled: true,
      tool_capabilities_enabled: true,
      include_mandates: true,
      include_guardrails: true,
      include_references: true,
      reference_index_enabled: true,
      continuity_enabled: true,
      continuity_max_sessions: 5,
      audience_tags: [],
      exclude_tags: [],
      exclude_memory_uuids: [],
    },
    max_concurrency: 4,
    max_subagent_concurrency: 2,
    daily_token_budget: 200000,
    hourly_request_limit: 50,
    version: 1,
    created_at: '2026-03-06T14:00:00Z',
    updated_at: '2026-03-06T14:00:00Z',
    ...overrides,
  }
}

describe('agent form helpers', () => {
  it('creates editable form data from an agent', () => {
    const formData = createAgentFormData(makeAgent())

    expect(formData.name).toBe('Persona')
    expect(formData.primary_model_id).toBe('claude-sonnet-4-6')
    expect(formData.effective_memory_config).toEqual(
      makeAgent().effective_memory_config,
    )
    expect(formData.max_concurrency).toBe(4)
    expect(formData.daily_token_budget).toBe(200000)
  })

  it('preserves strategies in form state and update payloads', () => {
    const strategies = {
      committee: {
        orchestrator: {
          agent_slug: 'investment-committee',
          model_id: 'codex/gpt-5.4',
          instruction: 'Synthesize committee output.',
        },
        seats: [
          {
            key: 'macro',
            label: 'Macro',
            enabled: true,
            agent_slug: 'market-pulse-analyst',
            model_id: 'codex/gpt-5.4',
            instruction: 'Focus on macro regime.',
            weight: 1,
          },
        ],
      },
    }

    const formData = createAgentFormData(makeAgent({ strategies }))
    expect(formData.strategies).toEqual(strategies)

    const payload = buildAgentUpdatePayload({ strategies })
    expect(payload.strategies).toEqual(strategies)
  })

  it('strips empty required fields from update payloads', () => {
    const payload = buildAgentUpdatePayload({
      name: '',
      system_prompt: '',
      primary_model_id: '',
      description: '',
      max_concurrency: 6,
      hourly_request_limit: 30,
    })

    expect(payload).toEqual({
      description: '',
      max_concurrency: 6,
      hourly_request_limit: 30,
    })
  })

  it('preserves memory_config as a single payload', () => {
    const memoryConfig = {
      injection_enabled: false,
      project_index_enabled: true,
      tool_capabilities_enabled: true,
      include_mandates: false,
      include_guardrails: false,
      include_references: false,
      reference_index_enabled: false,
      continuity_enabled: false,
      continuity_max_sessions: 5,
      audience_tags: [],
      exclude_tags: [],
      exclude_memory_uuids: [],
    }

    const payload = buildAgentUpdatePayload({
      name: 'Note Titler',
      primary_model_id: 'gemini-2.5-flash-lite',
      memory_config: memoryConfig,
    })

    expect(payload.memory_config).toEqual(memoryConfig)
  })

  it('uses the backend effective config as the inherited baseline', () => {
    const formData = createAgentFormData(
      makeAgent({
        effective_memory_config: {
          injection_enabled: false,
          project_index_enabled: true,
          tool_capabilities_enabled: true,
          include_mandates: false,
          include_guardrails: false,
          include_references: false,
          reference_index_enabled: false,
          continuity_enabled: false,
          continuity_max_sessions: 7,
          audience_tags: ['voice'],
          exclude_tags: ['draft'],
          exclude_memory_uuids: [],
        },
      }),
    )

    expect(formData.memory_config).toBeNull()
    expect(formData.effective_memory_config).toEqual({
      injection_enabled: false,
      project_index_enabled: true,
      tool_capabilities_enabled: true,
      include_mandates: false,
      include_guardrails: false,
      include_references: false,
      reference_index_enabled: false,
      continuity_enabled: false,
      continuity_max_sessions: 7,
      audience_tags: ['voice'],
      exclude_tags: ['draft'],
      exclude_memory_uuids: [],
    })
  })

  it('normalizes sparse agent memory config against the backend effective config', () => {
    const formData = createAgentFormData(
      makeAgent({
        memory_config: {
          include_references: true,
          cross_project_enabled: true,
        } as unknown as Agent['memory_config'],
        effective_memory_config: {
          injection_enabled: false,
          project_index_enabled: true,
          tool_capabilities_enabled: true,
          include_mandates: false,
          include_guardrails: false,
          include_references: false,
          reference_index_enabled: false,
          continuity_enabled: false,
          continuity_max_sessions: 6,
          audience_tags: [],
          exclude_tags: ['draft'],
          exclude_memory_uuids: [],
        },
      }),
    )

    expect(formData.memory_config).toEqual({
      injection_enabled: false,
      project_index_enabled: true,
      tool_capabilities_enabled: true,
      include_mandates: false,
      include_guardrails: false,
      include_references: false,
      reference_index_enabled: false,
      continuity_enabled: false,
      continuity_max_sessions: 6,
      audience_tags: [],
      exclude_tags: ['draft'],
      exclude_memory_uuids: [],
      cross_project_enabled: true,
    })
  })

  it('strips effective_memory_config from update payloads', () => {
    const payload = buildAgentUpdatePayload({
      name: 'Voice Responder',
      primary_model_id: 'claude-sonnet-4-6',
      effective_memory_config: makeAgent().effective_memory_config,
    })

    expect(payload.effective_memory_config).toBeUndefined()
  })
})
