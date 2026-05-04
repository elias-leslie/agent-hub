import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import PersonaAnalyticsPage from '@/app/persona/analytics/page'

vi.mock(
  '@/app/persona/analytics/components/PersonaImprovementDashboard',
  () => ({
    PersonaImprovementDashboard: () => <div>persona-improvement-dashboard</div>,
  }),
)

describe('PersonaAnalyticsPage', () => {
  it('renders the dedicated persona improvement dashboard', () => {
    render(<PersonaAnalyticsPage />)

    expect(
      screen.getByText('persona-improvement-dashboard'),
    ).toBeInTheDocument()
  })
})
