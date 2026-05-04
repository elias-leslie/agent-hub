import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { BudgetUsageDisplay } from '@/components/memory/BudgetUsageDisplay'

const usage = {
  mandates_tokens: 120,
  guardrails_tokens: 45,
  reference_tokens: 0,
  continuity_tokens: 32,
  total_tokens: 197,
  mandates_injected: 3,
  mandates_total: 4,
  guardrails_injected: 2,
  guardrails_total: 2,
  reference_injected: 0,
  reference_total: 8,
}

describe('BudgetUsageDisplay', () => {
  it('shows rendered token and reference coverage totals', () => {
    render(<BudgetUsageDisplay usage={usage} continuityEnabled={true} />)

    expect(screen.getByText('197')).toBeInTheDocument()
    expect(screen.getByText('References')).toBeInTheDocument()
    expect(screen.getByText('0/8')).toBeInTheDocument()
  })
})
