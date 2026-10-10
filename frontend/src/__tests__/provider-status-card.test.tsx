import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ProviderStatusCard } from '@/components/dashboard/ProviderStatusCard'

describe('ProviderStatusCard', () => {
  it('shows a ready provider without invented metrics', () => {
    render(
      <ProviderStatusCard
        provider={{
          name: 'codex',
          available: true,
          configured: true,
          error: null,
          health: null,
        }}
      />,
    )
    expect(screen.getByText('Ready')).toBeInTheDocument()
    expect(screen.queryByText(/avail/)).not.toBeInTheDocument()
  })

  it('shows why an unavailable provider cannot take requests', () => {
    const reason = 'no credential is stored for provider xai'
    render(
      <ProviderStatusCard
        provider={{
          name: 'xai',
          available: false,
          configured: false,
          error: reason,
          health: null,
        }}
      />,
    )
    expect(screen.getByText('xAI')).toBeInTheDocument()
    expect(screen.getByText('Unavailable')).toBeInTheDocument()
    expect(screen.getByText(reason)).toHaveAttribute('title', reason)
  })
})
