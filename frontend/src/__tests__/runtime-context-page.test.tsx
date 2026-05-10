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
  consumer_profile: 'agent_startup',
  project_id: null,
  query: 'startup context',
  total_tokens: 42,
  budget_tokens: 3500,
  rendered: '## Agentic CLI Startup Core\nDirect concise.',
  blocks: [
    {
      id: 'prompt:agentic-cli-startup-core',
      source_type: 'prompt' as const,
      source_id: 'agentic-cli-startup-core',
      title: 'Agentic CLI Startup Core',
      content: 'Direct concise.',
      token_count: 3,
      origin: 'auto' as const,
      source: 'auto' as const,
      auto_reason: 'boot_eligible',
      mode: 'order' as const,
      position: 10,
      tier: null,
      scope: 'global',
      tags: ['runtime_context'],
    },
    {
      id: 'memory:mem-1',
      source_type: 'memory' as const,
      source_id: 'mem-1',
      title: 'Use st',
      content: 'Use st for covered workflows.',
      token_count: 7,
      origin: 'auto' as const,
      source: 'auto' as const,
      auto_reason: 'tier:mandate',
      mode: 'order' as const,
      position: 100,
      tier: 'mandate',
      render_tier: 'L1' as const,
      scope: 'global',
      tags: [],
    },
  ],
  excluded: [],
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
        boot_eligible: true,
        exclude_agents: [],
        owner_agent_slug: null,
        prompt_type: 'runtime_context',
        deletion_locked: false,
        created_at: '2026-05-09T00:00:00Z',
        updated_at: '2026-05-09T00:00:00Z',
      },
    ])
    vi.mocked(fetchMemoryList).mockResolvedValue({
      episodes: [
        {
          uuid: 'mem-1',
          name: 'use-st',
          content:
            'FULL: Use st for every covered workflow including build, test, lint, and commit.',
          source: 'system',
          category: 'mandate',
          scope: 'global',
          scope_id: null,
          source_description: null,
          created_at: '2026-05-09T00:00:00Z',
          updated_at: '2026-05-09T00:00:00Z',
          version: null,
          valid_at: '2026-05-09T00:00:00Z',
          entities: [],
          summary: 'Use st (library)',
          loaded_count: 0,
          referenced_count: 0,
          helpful_count: 0,
          harmful_count: 0,
          utility_score: 0,
          tags: [],
        } as never,
      ],
      total: 1,
      cursor: null,
      has_more: false,
    })
  })

  it('renders the boot reactor topbar and rendered blocks', async () => {
    renderPage()

    await waitFor(() => {
      expect(
        screen.getAllByText('Agentic CLI Startup Core').length,
      ).toBeGreaterThan(0)
      expect(screen.getByText('Use st')).toBeInTheDocument()
    })
    // Token gauge surfaces both used and budget within the gauge region.
    const gauge = screen.getByLabelText('Token gauge')
    expect(gauge).toHaveTextContent('42')
    expect(gauge).toHaveTextContent('3,500 tok')
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

  it('renders memory body inline but collapses prompt body by default on rendered rows', async () => {
    renderPage()

    await waitFor(() => {
      expect(screen.getByText('Use st')).toBeInTheDocument()
    })

    const inlineBodies = screen.getAllByTestId('rendered-body-inline')
    // Prompts collapse by default; only the memory body is inline at first.
    expect(inlineBodies).toHaveLength(1)
    expect(inlineBodies[0].textContent).toBe('Use st for covered workflows.')
    expect(screen.queryByText('Direct concise.')).not.toBeInTheDocument()
  })

  it('exposes a chevron on prompts (collapse) and on compact memory rows (swap)', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('Use st')).toBeInTheDocument())

    // Prompts in Rendered get a "Show prompt body" chevron (collapsed default).
    expect(screen.getByTitle('Show prompt body')).toBeInTheDocument()
    // Compact memory keeps the "Expand to full content" swap chevron.
    expect(screen.getByTitle('Expand to full content')).toBeInTheDocument()
    expect(screen.queryByTitle('Show rendered version')).not.toBeInTheDocument()
  })

  it('reveals prompt body when its chevron is clicked', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('Use st')).toBeInTheDocument())

    fireEvent.click(screen.getByTitle('Show prompt body'))

    await waitFor(() => {
      const bodies = screen.getAllByTestId('rendered-body-inline')
      // Memory body + revealed prompt body.
      expect(bodies).toHaveLength(2)
      expect(bodies.some((el) => el.textContent === 'Direct concise.')).toBe(
        true,
      )
      expect(screen.getByTitle('Hide prompt body')).toBeInTheDocument()
    })
  })

  it('swaps body text to full content when chevron is clicked on a compact row', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('Use st')).toBeInTheDocument())

    const memoryBody = screen
      .getAllByTestId('rendered-body-inline')
      .find((el) => el.textContent === 'Use st for covered workflows.')
    expect(memoryBody).toBeDefined()

    const expand = screen.getByTitle('Expand to full content')
    fireEvent.click(expand)

    await waitFor(() => {
      // Memory body still the only inline row (prompt stays collapsed).
      expect(screen.getAllByTestId('rendered-body-inline')).toHaveLength(1)
      expect(memoryBody?.textContent).toBe(
        'FULL: Use st for every covered workflow including build, test, lint, and commit.',
      )
      // FULL meta badge appears while swapped.
      expect(screen.getByText('FULL')).toBeInTheDocument()
      // Chevron toggles to its "back to rendered" state.
      expect(screen.getByTitle('Show rendered version')).toBeInTheDocument()
    })
  })

  it('saves an exclude override when ✕ is clicked on a rendered row', async () => {
    renderPage()

    await waitFor(() => {
      expect(screen.getByText('Use st')).toBeInTheDocument()
    })
    const excludeButtons = screen.getAllByTitle('Exclude from boot context')
    // Click the memory row's exclude (last rendered row).
    fireEvent.click(excludeButtons[excludeButtons.length - 1])

    await waitFor(() => {
      expect(replaceRuntimeOverrides).toHaveBeenCalledWith(
        expect.objectContaining({
          consumerProfile: 'agent_startup',
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
