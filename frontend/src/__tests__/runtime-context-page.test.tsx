import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import RuntimeContextPage from '@/app/runtime-context/page'
import { ToastProvider } from '@/components/error/toast'
import { fetchPrompts } from '@/lib/api/prompts'
import {
  fetchRuntimeOverrides,
  fetchRuntimePreview,
  replaceRuntimeOverrides,
} from '@/lib/api/runtime-context'
import { fetchMemoryList } from '@/lib/memory/episodes'
import { createQueryClientWrapper } from './test-utils'

vi.mock('@/lib/api/runtime-context', () => ({
  fetchRuntimeOverrides: vi.fn(),
  fetchRuntimePreview: vi.fn(),
  replaceRuntimeOverrides: vi.fn(),
}))

vi.mock('@/lib/api/prompts', () => ({
  fetchPrompts: vi.fn(),
}))

vi.mock('@/lib/memory/episodes', () => ({
  fetchMemoryList: vi.fn(),
}))

const preview = {
  consumer_profile: 'codex_startup',
  project_id: null,
  query: 'startup context',
  total_tokens: 42,
  rendered: '## Agentic CLI Startup Core\nDirect concise.',
  blocks: [
    {
      id: 'prompt:agentic-cli-startup-core',
      source_type: 'prompt' as const,
      source_id: 'agentic-cli-startup-core',
      title: 'Agentic CLI Startup Core',
      content: 'Direct concise.',
      token_count: 3,
      origin: 'override' as const,
      mode: 'include' as const,
      position: 10,
      tier: null,
    },
    {
      id: 'memory:mem-1',
      source_type: 'memory' as const,
      source_id: 'mem-1',
      title: 'Use st',
      content: 'Use st for covered workflows.',
      token_count: 7,
      origin: 'auto' as const,
      mode: 'order' as const,
      position: 100,
      tier: 'mandate',
    },
  ],
  overrides: [],
}

function renderPage() {
  const QueryWrapper = createQueryClientWrapper()
  return render(
    <QueryWrapper>
      <ToastProvider>
        <RuntimeContextPage />
      </ToastProvider>
    </QueryWrapper>,
  )
}

describe('RuntimeContextPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(fetchRuntimeOverrides).mockResolvedValue([])
    vi.mocked(fetchRuntimePreview).mockResolvedValue(preview)
    vi.mocked(replaceRuntimeOverrides).mockResolvedValue([])
    vi.mocked(fetchPrompts).mockResolvedValue([
      {
        id: 1,
        slug: 'agentic-cli-startup-core',
        name: 'Agentic CLI Startup Core',
        content: 'Direct concise.',
        description: null,
        is_global: true,
        enabled: true,
        exclude_agents: [],
        owner_agent_slug: null,
        prompt_type: 'runtime_context',
        deletion_locked: false,
        created_at: '2026-05-09T00:00:00Z',
        updated_at: '2026-05-09T00:00:00Z',
      },
    ])
    vi.mocked(fetchMemoryList).mockResolvedValue({
      episodes: [],
      total: 0,
      cursor: null,
      has_more: false,
    })
  })

  it('renders preview blocks and rendered context', async () => {
    renderPage()

    await waitFor(() => {
      expect(
        screen.getAllByText('Agentic CLI Startup Core').length,
      ).toBeGreaterThan(0)
      expect(screen.getByText('Use st')).toBeInTheDocument()
    })
    expect(screen.getAllByText('42 tokens').length).toBeGreaterThan(0)
    expect(screen.getAllByText(/Direct concise/).length).toBeGreaterThan(0)
  })

  it('does not expose profile/project/query controls', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('Use st')).toBeInTheDocument())
    expect(screen.queryByText(/^Profile$/)).not.toBeInTheDocument()
    expect(screen.queryByText(/^Project$/)).not.toBeInTheDocument()
    expect(screen.queryByText(/^Query$/)).not.toBeInTheDocument()
    expect(screen.queryByText(/^Task Type$/)).not.toBeInTheDocument()
    expect(screen.queryByText(/^Phase$/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Override Layer/)).not.toBeInTheDocument()
  })

  it('saves an exclude override from the block list', async () => {
    renderPage()

    await waitFor(() => {
      expect(screen.getByText('Use st')).toBeInTheDocument()
    })
    // Memory row's exclude toggle (prompt row is index 0).
    const excludeButtons = screen.getAllByTitle('Exclude')
    fireEvent.click(excludeButtons[excludeButtons.length - 1])

    await waitFor(() => {
      expect(replaceRuntimeOverrides).toHaveBeenCalledWith(
        expect.objectContaining({
          consumerProfile: 'codex_startup',
          overrides: expect.arrayContaining([
            expect.objectContaining({
              source_type: 'memory',
              source_id: 'mem-1',
              mode: 'exclude',
            }),
          ]),
        }),
      )
    })
    const lastCall = vi.mocked(replaceRuntimeOverrides).mock.calls.at(-1)?.[0]
    expect(lastCall?.projectId).toBeUndefined()
  })
})
