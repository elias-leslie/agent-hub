import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ModelCard } from '@/components/models/model-card'
import { codexModel } from './agent-model-fixtures'

describe('ModelCard context window', () => {
  it('shows the size for a chat model', () => {
    render(<ModelCard model={codexModel} />)
    expect(screen.getByText('1050K')).toBeInTheDocument()
  })

  it('says n/a instead of 0K for a model without a context window', () => {
    render(<ModelCard model={{ ...codexModel, context_window: 0 }} />)
    expect(screen.getByText('n/a')).toBeInTheDocument()
    expect(screen.queryByText('0K')).not.toBeInTheDocument()
  })
})

describe('ModelCard billing route', () => {
  // The same model from Codex (ChatGPT plan) and the OpenAI API must not read as duplicates.
  it.each([
    'codex_oauth_subscription; verified_2026-10-09',
    'codex_oauth; text_verified_2026-10-28; vision_tools_untested',
  ])('labels a Codex model as the subscription (%s)', (availability) => {
    render(<ModelCard model={{ ...codexModel, availability }} />)
    expect(screen.getByText('Codex subscription')).toBeInTheDocument()
    expect(screen.getByText('Subscription')).toBeInTheDocument()
    expect(
      screen.getByText('API equivalent $2.50 / $15.00'),
    ).toBeInTheDocument()
  })

  it('labels the OpenAI API model as paid', () => {
    render(
      <ModelCard
        model={{
          ...codexModel,
          id: 'openai/gpt-6.1-terra',
          provider: 'openai',
          availability:
            'chat_completions_without_tools; api_entitlement_unverified',
        }}
      />,
    )
    expect(screen.getByText('OpenAI API, paid')).toBeInTheDocument()
    expect(screen.getByText('OpenAI')).toBeInTheDocument()
    expect(screen.queryByText('Codex subscription')).not.toBeInTheDocument()
  })
})
