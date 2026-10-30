import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import {
  ModelSelect,
  modelOptionLabels,
} from '@/app/agents/[slug]/components/ModelSelect'
import { codexModel } from './agent-model-fixtures'

const terraCodex = {
  ...codexModel,
  id: 'codex/gpt-6.1-terra',
  name: 'GPT-6.1 Terra',
}
const terraOpenai = {
  ...codexModel,
  id: 'openai/gpt-6.1-terra',
  name: 'GPT-6.1 Terra',
  provider: 'openai',
}

describe('model option labels', () => {
  it('adds the provider only to names that two providers share', () => {
    const labels = modelOptionLabels([codexModel, terraCodex, terraOpenai])
    expect(labels.get(codexModel.id)).toBe(codexModel.name)
    expect(labels.get(terraCodex.id)).toBe('GPT-6.1 Terra (Codex)')
    expect(labels.get(terraOpenai.id)).toBe('GPT-6.1 Terra (OpenAI)')
  })

  it('shows the told-apart names in the primary model picker', () => {
    render(
      <ModelSelect
        value={terraOpenai.id}
        onChange={vi.fn()}
        label="Primary model"
        models={[codexModel, terraCodex, terraOpenai]}
      />,
    )
    expect(
      screen.getByRole('option', { name: 'GPT-6.1 Terra (Codex)' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('option', { name: 'GPT-6.1 Terra (OpenAI)' }),
    ).toBeInTheDocument()
  })
})
