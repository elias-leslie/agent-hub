import { renderHook } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { useAgentFiltering } from '@/app/agents/hooks/useAgentFiltering'
import type { Agent } from '@/app/agents/lib/types'
import { getPersonaDisplayName } from '@/hooks/use-persona-display-name'

function agent(slug: string, name: string): Agent {
  return {
    id: slug.length,
    slug,
    name,
    description: null,
    primary_model_id: 'gpt-5.4',
    fallback_models: [],
    temperature: 0.2,
    is_active: true,
    is_coding_agent: false,
    version: 1,
    created_at: '2026-03-01T00:00:00Z',
    updated_at: '2026-03-02T00:00:00Z',
  }
}

describe('agent list filtering', () => {
  it('lists the persona agent like any other agent', () => {
    const { result } = renderHook(() =>
      useAgentFiltering({
        agents: [agent('persona', 'Persona'), agent('builder', 'Builder')],
        searchQuery: '',
        sortField: 'name',
        sortDirection: 'asc',
        metricsData: undefined,
      }),
    )

    expect(result.current.map((a) => a.slug)).toEqual(['builder', 'persona'])
  })
})

describe('persona display name', () => {
  it('uses the persona row name and falls back when it is blank', () => {
    expect(getPersonaDisplayName('  Jenny ')).toBe('Jenny')
    expect(getPersonaDisplayName('   ')).toBe('Persona')
    expect(getPersonaDisplayName(undefined)).toBe('Persona')
  })
})
