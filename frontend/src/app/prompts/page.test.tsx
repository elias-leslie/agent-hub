import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { fetchPrompts, type Prompt } from '@/lib/api/prompts'
import PromptsPage from './page'

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/lib/api/prompts', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/api/prompts')>()),
  fetchPrompts: vi.fn(),
}))

const prompt = (overrides: Partial<Prompt>): Prompt => ({
  id: 1,
  slug: 'p',
  name: 'P',
  content: '',
  description: null,
  is_global: false,
  enabled: true,
  exclude_agents: [],
  owner_agent_slug: null,
  prompt_type: 'standard',
  deletion_locked: false,
  created_at: '2026-10-27T00:00:00Z',
  updated_at: '2026-10-27T00:00:00Z',
  ...overrides,
})

const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={new QueryClient()}>
    {children}
  </QueryClientProvider>
)

describe('Prompts list scope', () => {
  it('names the project a project-scoped prompt applies to', async () => {
    vi.mocked(fetchPrompts).mockResolvedValue([
      prompt({
        slug: 'agent-hub-development-policy',
        name: 'Agent Hub Development Policy',
        projects: ['agent-hub'],
      }),
      prompt({ id: 2, slug: 'g', name: 'Global one', is_global: true }),
    ])
    render(<PromptsPage />, { wrapper })
    expect(await screen.findByText('Project: agent-hub')).toBeInTheDocument()
    expect(screen.getAllByText(/^Project:/)).toHaveLength(1)
  })
})
