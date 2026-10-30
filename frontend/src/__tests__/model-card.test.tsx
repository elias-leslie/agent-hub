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
