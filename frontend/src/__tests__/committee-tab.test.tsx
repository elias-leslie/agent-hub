import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { CommitteeTab } from '@/app/agents/[slug]/components/CommitteeTab'
import type { Agent, ModelInfo } from '@/app/agents/[slug]/types'
import { codexModel } from './agent-model-fixtures'

const fetchApiMock = vi.fn()

vi.mock('@/lib/api-config', () => ({
  fetchApi: (...args: unknown[]) => fetchApiMock(...args),
}))

const models: ModelInfo[] = [
  codexModel,
  {
    id: 'claude-opus-4-7',
    name: 'Claude Opus 4.7',
    provider: 'claude',
    alias: 'opus-4.7',
    hint: 'Frontier',
    cost: {
      input_per_m: 15,
      output_per_m: 75,
      pricing_unit: 'per_million_tokens',
      unit_price: null,
      source: 'catalog',
    },
    scores: {
      coding: 85,
      reasoning: 92,
      planning: 90,
      tool_use: 84,
      instruction: 91,
      design: 88,
      composite: 88,
    },
    context_window: 400_000,
    speed_tier: 'slow',
    capabilities: {
      can_generate_images: false,
      has_vision: true,
      can_edit_images: false,
      has_thinking: true,
      supports_pdf: true,
      supports_audio: false,
      max_output_tokens: 32768,
      supports_tool_execution: true,
      supports_verbosity: true,
      supports_xhigh: true,
      supports_session_cache: true,
    },
  },
]

const formData: Partial<Agent> = {
  strategies: {},
}

describe('committee tab', () => {
  beforeEach(() => {
    fetchApiMock.mockReset()
  })

  it('renders default committee seats and persists strategy updates', () => {
    const updateField = vi.fn()

    render(
      <CommitteeTab
        formData={formData}
        updateField={updateField}
        availableModels={models}
      />,
    )

    expect(screen.getByText('Market Prediction Committee')).toBeInTheDocument()
    expect(screen.getByLabelText('Macro seat model')).toHaveValue('')

    fireEvent.change(screen.getByLabelText('Macro seat model'), {
      target: { value: 'claude-opus-4-7' },
    })

    expect(updateField).toHaveBeenCalledWith(
      'strategies',
      expect.objectContaining({
        committee: expect.objectContaining({
          seats: expect.arrayContaining([
            expect.objectContaining({
              key: 'macro',
              model_id: 'claude-opus-4-7',
            }),
          ]),
        }),
      }),
    )
  })

  it('runs a validation roundtable and renders the returned headline', async () => {
    fetchApiMock.mockResolvedValue({
      ok: true,
      json: async () => ({
        committee_summary: { headline: 'Constructive risk appetite' },
        calls: [],
        votes: [],
      }),
    })

    render(
      <CommitteeTab
        formData={formData}
        updateField={vi.fn()}
        availableModels={models}
      />,
    )

    fireEvent.click(
      screen.getByRole('button', { name: /run validation roundtable/i }),
    )

    await waitFor(() => {
      expect(fetchApiMock).toHaveBeenCalled()
    })
    expect(
      screen.getAllByText(/constructive risk appetite/i).length,
    ).toBeGreaterThan(0)
  })
})
