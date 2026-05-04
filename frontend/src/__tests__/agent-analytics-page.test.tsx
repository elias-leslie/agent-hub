import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import AgentAnalyticsPage from '@/app/agents/[slug]/analytics/page'

vi.mock('next/navigation', () => ({
  useParams: () => ({ slug: 'persona' }),
}))

const mockArenaDashboard = vi.fn(
  ({
    slug,
    backHref,
    initialView,
  }: {
    slug: string
    backHref?: string
    initialView?: string
  }) => (
    <div>
      arena:{slug}:{backHref ?? 'none'}:{initialView ?? 'none'}
    </div>
  ),
)

vi.mock('@/app/agents/[slug]/arena/components/AgentArenaDashboard', () => ({
  AgentArenaDashboard: (props: {
    slug: string
    backHref?: string
    initialView?: string
  }) => mockArenaDashboard(props),
}))

describe('AgentAnalyticsPage', () => {
  it('uses Arena as the analytics compatibility surface with the runtime view selected', () => {
    render(<AgentAnalyticsPage />)

    expect(screen.getByText('arena:persona:none:runtime')).toBeInTheDocument()
    expect(mockArenaDashboard).toHaveBeenCalledWith(
      expect.objectContaining({
        slug: 'persona',
        initialView: 'runtime',
      }),
    )
  })
})
