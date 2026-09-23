import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import RuntimeContextPage from '@/app/runtime-context/page'
import {
  type ContextInventory,
  contextRequest,
} from '@/lib/api/context-management'
import { fetchProjectCatalog } from '@/lib/api/project-permissions'
import { getModels } from '@/lib/models'
import { createQueryClientWrapper } from './test-utils'

vi.mock('@/lib/api/context-management', () => ({ contextRequest: vi.fn() }))
vi.mock('@/lib/api/project-permissions', () => ({
  fetchProjectCatalog: vi.fn(),
}))
vi.mock('@/lib/models', () => ({ getModels: vi.fn() }))
vi.mock('@/lib/api/agents', () => ({
  fetchAgents: vi.fn().mockResolvedValue({ agents: [] }),
}))
const inventory: ContextInventory = {
  sources: [
    {
      source_type: 'prompt',
      source_id: 'research',
      name: 'Security Research',
      content: 'Project-specific research policy.',
      summary: '',
      enabled: true,
      owner_agent_id: null,
      authority: 'standard',
      revision: 'sha256:original',
      state: 'not applicable',
      reason: 'outside source scope',
      tokens: 12,
      rendered: null,
      review_status: null,
      policy: {
        scope: 'project',
        targets: ['security-research'],
        workflows: ['security-research'],
        activation: 'always',
        task_types: [],
        phases: [],
        applicability: {},
        required: true,
        format: 'full',
      },
    },
  ],
  delivery: {
    status: 'ok',
    rendered: 'Required global rules and ST essentials.',
    estimated_tokens: 400,
    delivery_id: 'generated-1',
  },
  placements: [],
  placement_revision: 'placement-1',
}
function renderPage() {
  const Wrapper = createQueryClientWrapper()
  return render(
    <Wrapper>
      <RuntimeContextPage />
    </Wrapper>,
  )
}

describe('Canonical context management', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getModels).mockResolvedValue([])
    vi.mocked(fetchProjectCatalog).mockResolvedValue([
      {
        project_id: 'agent-hub',
        label: 'Agent Hub',
        root_path: '/srv/agent-hub',
        has_permission: true,
        has_root: true,
        has_memory: true,
        sources: [],
      },
      {
        project_id: 'security-research',
        label: 'Security Research project',
        root_path: '/srv/security-research',
        has_permission: true,
        has_root: true,
        has_memory: true,
        sources: [],
      },
    ])
    vi.mocked(contextRequest).mockImplementation(async (path) => {
      if (path.startsWith('/history')) return []
      if (path === '/preview')
        return { ...inventory, token_delta: -12, baseline: inventory.delivery }
      return inventory
    })
  })

  it('shows scope and why a source is absent without treating generated text as delivered', async () => {
    renderPage()
    expect(
      await screen.findByRole('button', { name: 'Security Research' }),
    ).toBeInTheDocument()
    expect(screen.getAllByText('not applicable').length).toBeGreaterThan(0)
    expect(screen.getByText('outside source scope')).toBeInTheDocument()
    fireEvent.click(
      screen.getByRole('button', { name: 'Exact rendered context' }),
    )
    expect(screen.getByText(/Generated preview only/)).toBeInTheDocument()
    expect(
      screen.getByText('Required global rules and ST essentials.'),
    ).toBeInTheDocument()
  })

  it('changing preview project never changes the source defaults', async () => {
    renderPage()
    await screen.findByRole('button', { name: 'Security Research' })
    fireEvent.change(screen.getByLabelText('Preview project'), {
      target: { value: 'agent-hub' },
    })
    await waitFor(() =>
      expect(contextRequest).toHaveBeenCalledWith(
        '/inventory',
        expect.objectContaining({ project_id: 'agent-hub' }),
      ),
    )
    expect(
      vi.mocked(contextRequest).mock.calls.some(([path]) => path === '/save'),
    ).toBe(false)
    expect(screen.getByText('0 staged changes')).toBeInTheDocument()
  })

  it('stages edits, requires preview, and sends the original revision for atomic save', async () => {
    renderPage()
    fireEvent.click(
      await screen.findByRole('button', { name: 'Security Research' }),
    )
    fireEvent.change(screen.getByLabelText('Applies to'), {
      target: { value: 'global' },
    })
    expect(
      screen.getByRole('button', { name: 'Save reviewed changes' }),
    ).toBeDisabled()
    expect(
      vi.mocked(contextRequest).mock.calls.some(([path]) => path === '/save'),
    ).toBe(false)
    fireEvent.click(screen.getByRole('button', { name: 'Preview changes' }))
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Save reviewed changes' }),
      ).toBeEnabled(),
    )
    expect(
      screen.getByText('Scope only. Content unchanged.'),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('region', { name: 'Staged change summary' }),
    ).toHaveTextContent('Security Research project → Every project')
    expect(contextRequest).toHaveBeenCalledWith(
      '/preview',
      expect.objectContaining({
        edits: [
          expect.objectContaining({
            source_id: 'research',
            expected_revision: 'sha256:original',
            policy: expect.objectContaining({ scope: 'global', targets: [] }),
          }),
        ],
      }),
    )
    fireEvent.click(
      screen.getByRole('button', { name: 'Save reviewed changes' }),
    )
    await screen.findByText(/Saved. Changes apply to future context generation/)
  })

  it('retains a stale draft after the server rejects it', async () => {
    renderPage()
    fireEvent.click(
      await screen.findByRole('button', { name: 'Security Research' }),
    )
    fireEvent.click(screen.getByText('Actions'))
    fireEvent.click(
      screen.getByRole('button', { name: 'Disable source everywhere' }),
    )
    fireEvent.click(screen.getByRole('button', { name: 'Preview changes' }))
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Save reviewed changes' }),
      ).toBeEnabled(),
    )
    vi.mocked(contextRequest).mockImplementation(async (path) => {
      if (path === '/save')
        throw new Error('Source changed. Reload and review the new revision.')
      if (path.startsWith('/history')) return []
      return inventory
    })
    fireEvent.click(
      screen.getByRole('button', { name: 'Save reviewed changes' }),
    )
    expect(await screen.findByRole('alert')).toHaveTextContent('Source changed')
    expect(screen.getByText('1 staged changes')).toBeInTheDocument()
  })
  it('opens with the basic editor and keeps policy and destructive controls in disclosures', async () => {
    renderPage()
    fireEvent.click(
      await screen.findByRole('button', { name: 'Security Research' }),
    )
    const inspector = screen.getByRole('complementary', {
      name: 'Inspect Security Research',
    })
    expect(within(inspector).getByLabelText('Name')).toHaveValue(
      'Security Research',
    )
    expect(within(inspector).getByLabelText('Content')).toHaveValue(
      'Project-specific research policy.',
    )
    expect(within(inspector).getByLabelText('Applies to')).toHaveValue(
      'project',
    )
    expect(within(inspector).getByLabelText('Loads when')).not.toBeVisible()
    expect(
      within(inspector).getByRole('button', {
        name: 'Disable source everywhere',
      }),
    ).not.toBeVisible()
    expect(
      within(inspector).getByText('Required rule · Workflow rules'),
    ).toBeVisible()
    fireEvent.click(within(inspector).getByText('Advanced rules'))
    expect(within(inspector).getByLabelText('Loads when')).toBeVisible()
    expect(within(inspector).getByLabelText('Delivered format')).toBeDisabled()
    fireEvent.click(within(inspector).getByRole('button', { name: 'history' }))
    expect(
      within(inspector).getByText(/No context-management history yet/),
    ).toBeVisible()
  })

  it('selects projects by name and removes targets while preserving every advanced rule', async () => {
    renderPage()
    fireEvent.click(
      await screen.findByRole('button', { name: 'Security Research' }),
    )
    fireEvent.change(screen.getByLabelText('Find a project'), {
      target: { value: 'Agent Hub' },
    })
    fireEvent.click(
      screen.getByRole('button', { name: 'Remove project security-research' }),
    )
    expect(screen.getByLabelText('Find a project')).toHaveValue('')
    fireEvent.click(screen.getByRole('button', { name: 'Preview changes' }))
    await waitFor(() =>
      expect(contextRequest).toHaveBeenCalledWith(
        '/preview',
        expect.objectContaining({
          edits: [
            expect.objectContaining({
              expected_revision: 'sha256:original',
              policy: {
                ...inventory.sources[0].policy,
                targets: ['agent-hub'],
              },
            }),
          ],
        }),
      ),
    )
    expect(screen.getByLabelText('Content')).toHaveValue(
      'Project-specific research policy.',
    )
    expect(
      screen.getByText('Scope only. Content unchanged.'),
    ).toBeInTheDocument()
  })

  it('keeps project placement beside the source preview and disables it without a project', async () => {
    renderPage()
    fireEvent.click(
      await screen.findByRole('button', { name: 'Security Research' }),
    )
    expect(
      screen.queryByRole('button', { name: 'Request here' }),
    ).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'preview' }))
    expect(screen.getByRole('button', { name: 'Request here' })).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Preview project'), {
      target: { value: 'agent-hub' },
    })
    expect(screen.getByRole('button', { name: 'Request here' })).toBeEnabled()
    fireEvent.click(screen.getByRole('button', { name: 'Request here' }))
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Preview changes' }),
      ).toBeEnabled(),
    )
    fireEvent.click(screen.getByRole('button', { name: 'Preview changes' }))
    await waitFor(() =>
      expect(contextRequest).toHaveBeenCalledWith(
        '/preview',
        expect.objectContaining({
          edits: [],
          placements: [
            { source_type: 'prompt', source_id: 'research', mode: 'include' },
          ],
        }),
      ),
    )
  })

  it('does not describe a content edit as scope only', async () => {
    renderPage()
    fireEvent.click(
      await screen.findByRole('button', { name: 'Security Research' }),
    )
    fireEvent.change(screen.getByLabelText('Applies to'), {
      target: { value: 'global' },
    })
    fireEvent.change(screen.getByLabelText('Content'), {
      target: { value: 'Updated research policy.' },
    })
    expect(
      screen.queryByText('Scope only. Content unchanged.'),
    ).not.toBeInTheDocument()
    expect(
      screen.getByRole('region', { name: 'Staged change summary' }),
    ).toHaveTextContent('Content, Applies to')
  })
  it('preserves advanced memory settings and exposes archive only through Actions', async () => {
    const memory = {
      ...inventory.sources[0],
      source_type: 'memory' as const,
      name: 'Project learning',
      policy: {
        ...inventory.sources[0].policy!,
        activation: 'relevant' as const,
        required: false,
        format: 'summary' as const,
        applicability: {
          consumer_surfaces: ['codex'],
          exclude_agent_slugs: ['curator'],
        },
      },
    }
    vi.mocked(contextRequest).mockImplementation(async (path) => {
      if (path.startsWith('/history')) return []
      return { ...inventory, sources: [memory] }
    })
    renderPage()
    fireEvent.click(
      await screen.findByRole('button', { name: 'Project learning' }),
    )
    expect(
      screen.getByRole('button', { name: 'Archive memory' }),
    ).not.toBeVisible()
    expect(
      screen.getByText(
        /When relevant · Summary · Workflow rules · Consumer targeting/,
      ),
    ).toBeVisible()
    fireEvent.change(screen.getByLabelText('Applies to'), {
      target: { value: 'global' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Preview changes' }))
    await waitFor(() =>
      expect(contextRequest).toHaveBeenCalledWith(
        '/preview',
        expect.objectContaining({
          edits: [
            expect.objectContaining({
              source_type: 'memory',
              policy: { ...memory.policy, scope: 'global', targets: [] },
            }),
          ],
        }),
      ),
    )
    fireEvent.click(screen.getByText('Actions'))
    expect(screen.getByRole('button', { name: 'Archive memory' })).toBeVisible()
    expect(
      screen.getByRole('button', { name: 'Save reviewed changes' }),
    ).toBeEnabled()
  })

  it('keeps computed sources read only in the basic editor', async () => {
    vi.mocked(contextRequest).mockImplementation(async (path) => {
      if (path.startsWith('/history')) return []
      return {
        ...inventory,
        sources: [
          {
            ...inventory.sources[0],
            source_type: 'computed',
            name: 'Capabilities',
            policy: null,
          },
        ],
      }
    })
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Capabilities' }))
    expect(screen.getByLabelText('Name')).toBeDisabled()
    expect(screen.getByLabelText('Content')).toBeDisabled()
    expect(screen.queryByText('Actions')).not.toBeInTheDocument()
  })
})
