import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { MemoryTab } from '@/app/agents/[slug]/components/MemoryTab'
import type { Agent } from '@/app/agents/[slug]/types'
import {
  fetchRuntimePolicy,
  updateRuntimePolicy,
} from '@/lib/api/runtime-context'
import { createQueryClientWrapper } from './test-utils'

vi.mock('@/lib/api/runtime-context', () => ({
  fetchRuntimePolicy: vi.fn(),
  updateRuntimePolicy: vi.fn(),
}))

const wrapper = createQueryClientWrapper()

beforeEach(() => {
  vi.mocked(fetchRuntimePolicy).mockResolvedValue({
    consumer_profile: 'agent_runtime',
    mandate_limit: 8,
    guardrail_limit: 16,
    reference_limit: 4,
  })
  vi.mocked(updateRuntimePolicy).mockResolvedValue({
    consumer_profile: 'agent_runtime',
    mandate_limit: 12,
    guardrail_limit: 16,
    reference_limit: 4,
  })
})

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
      { wrapper },
    )

    fireEvent.click(
      screen.getByRole('button', { name: 'Enable Custom Memory Settings' }),
    )

    expect(updateField).toHaveBeenCalledWith('memory_config', inheritedConfig)
  })

  it('clears subordinate options when memory injection is turned off', () => {
    const updateField = vi.fn()

    render(<MemoryTab formData={makeFormData()} updateField={updateField} />, {
      wrapper,
    })

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
      { wrapper },
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

  it('hides the "Edit profile defaults" link when custom settings are off', () => {
    const updateField = vi.fn()
    render(
      <MemoryTab
        formData={makeFormData({ memory_config: null })}
        updateField={updateField}
      />,
      { wrapper },
    )
    expect(
      screen.queryByRole('button', { name: /Edit profile defaults/ }),
    ).not.toBeInTheDocument()
  })

  it('opens the policy modal scoped to the inherited profile and saves caps', async () => {
    const updateField = vi.fn()
    render(
      <MemoryTab
        formData={makeFormData({
          memory_config: {
            injection_enabled: true,
            project_index_enabled: true,
            tool_capabilities_enabled: true,
            include_mandates: true,
            include_guardrails: true,
            include_references: true,
            reference_index_enabled: true,
            continuity_enabled: false,
            continuity_max_sessions: 5,
            audience_tags: [],
            exclude_tags: [],
            exclude_memory_uuids: [],
            runtime_consumer_profile: 'agent_coding',
          },
        })}
        updateField={updateField}
      />,
      { wrapper },
    )

    const link = screen.getByRole('button', {
      name: /Edit profile defaults/,
    })
    fireEvent.click(link)

    await waitFor(() => {
      expect(
        screen.getByText(/Context selection · agent_coding/),
      ).toBeInTheDocument()
    })

    await waitFor(() => {
      expect(fetchRuntimePolicy).toHaveBeenCalledWith({
        consumerProfile: 'agent_coding',
      })
    })

    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => {
      expect(updateRuntimePolicy).toHaveBeenCalledWith(
        expect.objectContaining({ consumerProfile: 'agent_coding' }),
      )
    })
  })

  it('falls back to agent_runtime when no profile override is set', async () => {
    const updateField = vi.fn()
    render(
      <MemoryTab
        formData={makeFormData({
          memory_config: {
            injection_enabled: true,
            project_index_enabled: true,
            tool_capabilities_enabled: true,
            include_mandates: true,
            include_guardrails: true,
            include_references: true,
            reference_index_enabled: true,
            continuity_enabled: false,
            continuity_max_sessions: 5,
            audience_tags: [],
            exclude_tags: [],
            exclude_memory_uuids: [],
          },
        })}
        updateField={updateField}
      />,
      { wrapper },
    )

    fireEvent.click(
      screen.getByRole('button', { name: /Edit profile defaults/ }),
    )

    await waitFor(() => {
      expect(
        screen.getByText(/Context selection · agent_runtime/),
      ).toBeInTheDocument()
    })
  })

  it('updates consumer profile overrides through routing inputs', () => {
    const updateField = vi.fn()

    render(<MemoryTab formData={makeFormData()} updateField={updateField} />, {
      wrapper,
    })

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
