import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { MemoryTab } from '@/app/agents/[slug]/components/MemoryTab'
import type { Agent } from '@/app/agents/[slug]/types'

function makeFormData(overrides: Partial<Agent> = {}): Partial<Agent> {
  return {
    memory_config: {
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
    ...overrides,
  }
}

describe('MemoryTab', () => {
  it('seeds custom settings from the effective backend config', () => {
    const updateField = vi.fn()
    const inheritedConfig = {
      injection_enabled: false,
      project_index_enabled: true,
      tool_capabilities_enabled: true,
      include_mandates: false,
      include_guardrails: false,
      include_references: false,
      reference_index_enabled: false,
      continuity_enabled: false,
      continuity_max_sessions: 7,
      audience_tags: [],
      exclude_tags: [],
      exclude_memory_uuids: [],
    }

    render(
      <MemoryTab
        formData={makeFormData({
          memory_config: null,
          effective_memory_config: inheritedConfig,
        })}
        updateField={updateField}
      />,
    )

    fireEvent.click(
      screen.getByRole('button', { name: 'Enable Custom Memory Settings' }),
    )

    expect(updateField).toHaveBeenCalledWith('memory_config', inheritedConfig)
  })

  it('clears subordinate options when memory injection is turned off', () => {
    const updateField = vi.fn()

    render(<MemoryTab formData={makeFormData()} updateField={updateField} />)

    fireEvent.click(screen.getByRole('button', { name: 'Memory Injection' }))

    expect(updateField).toHaveBeenCalledWith('memory_config', {
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
    })
  })

  it('disables subordinate controls when memory injection is already off', () => {
    const updateField = vi.fn()

    render(
      <MemoryTab
        formData={makeFormData({
          memory_config: {
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
          },
        })}
        updateField={updateField}
      />,
    )

    expect(
      screen.getByRole('button', { name: 'Include Mandates' }),
    ).toBeDisabled()
    expect(
      screen.getByRole('button', { name: 'Include Guardrails' }),
    ).toBeDisabled()
    expect(
      screen.getByRole('button', { name: 'Include References' }),
    ).toBeDisabled()
    expect(
      screen.getByRole('button', { name: 'Passive Reference Index' }),
    ).toBeDisabled()
    expect(
      screen.getByRole('button', { name: 'Session Continuity' }),
    ).toBeDisabled()
    expect(
      screen.getByRole('button', { name: 'Memory Injection' }),
    ).not.toBeDisabled()
  })

  it('updates consumer profile overrides through routing inputs', () => {
    const updateField = vi.fn()

    render(<MemoryTab formData={makeFormData()} updateField={updateField} />)

    fireEvent.change(screen.getByLabelText('Runtime Profile Override'), {
      target: { value: 'agent_coding' },
    })

    expect(updateField).toHaveBeenCalledWith('memory_config', {
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
      runtime_consumer_profile: 'agent_coding',
    })
  })
})
