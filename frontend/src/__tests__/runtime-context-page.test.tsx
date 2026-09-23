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
  type ContextSource,
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

const research: ContextSource = {
  source_type: 'prompt',
  source_id: 'research',
  name: 'Security Research',
  content: 'Project-specific research policy.',
  summary: '',
  enabled: true,
  owner_agent_id: null,
  authority: 'standard',
  revision: 'sha256:research',
  state: 'not applicable',
  reason: 'outside source scope',
  tokens: 12,
  rendered: null,
  review_status: null,
  policy: {
    scope: 'project',
    targets: ['security-research'],
    workflows: [],
    activation: 'always',
    task_types: [],
    phases: [],
    applicability: {},
    required: true,
    format: 'full',
  },
}
const operations: ContextSource = {
  ...research,
  source_id: 'operations',
  name: 'Operations Guide',
  content: 'Operational guidance.',
  revision: 'sha256:operations',
}
const computed: ContextSource = {
  ...research,
  source_type: 'computed',
  source_id: 'capabilities',
  name: 'Capabilities',
  policy: null,
}
const inventory: ContextInventory = {
  sources: [research, operations, computed],
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

function callsTo(path: string) {
  return vi
    .mocked(contextRequest)
    .mock.calls.filter(([actual]) => actual === path)
}

describe('Agent context', () => {
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
      return inventory
    })
  })

  it('shows context sources without review and maintenance features', async () => {
    renderPage()
    expect(
      await screen.findByRole('button', { name: 'Security Research' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Operations Guide' }),
    ).toBeInTheDocument()
    expect(screen.getAllByText('Does not apply here')).toHaveLength(3)
    expect(screen.queryByText('Context review')).not.toBeInTheDocument()
    expect(screen.queryByText('Context maintenance')).not.toBeInTheDocument()
    expect(callsTo('/review')).toHaveLength(0)
    expect(callsTo('/maintenance')).toHaveLength(0)
  })

  it('keeps multiple source rows open and preserves each unfinished edit', async () => {
    renderPage()
    fireEvent.click(
      await screen.findByRole('button', { name: 'Security Research' }),
    )
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }))
    fireEvent.change(screen.getByLabelText('Content'), {
      target: { value: 'Unsaved research update.' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Operations Guide' }))
    expect(
      screen.getByDisplayValue('Unsaved research update.'),
    ).toBeInTheDocument()
    const operationsRow = screen
      .getByRole('button', { name: 'Operations Guide' })
      .closest('[role="listitem"]') as HTMLElement
    fireEvent.click(within(operationsRow).getByRole('button', { name: 'Edit' }))
    fireEvent.change(within(operationsRow).getByLabelText('Content'), {
      target: { value: 'Unsaved operations update.' },
    })
    expect(
      screen.getByDisplayValue('Unsaved operations update.'),
    ).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Security Research' }))
    fireEvent.click(screen.getByRole('button', { name: 'Security Research' }))
    expect(
      screen.getByDisplayValue('Unsaved research update.'),
    ).toBeInTheDocument()
    expect(
      screen.getByDisplayValue('Unsaved operations update.'),
    ).toBeInTheDocument()
    expect(callsTo('/save')).toHaveLength(0)
  })

  it('saves one edited row directly with its original revision and no preview request', async () => {
    renderPage()
    fireEvent.click(
      await screen.findByRole('button', { name: 'Security Research' }),
    )
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }))
    fireEvent.change(screen.getByLabelText('Content'), {
      target: { value: 'Updated research policy.' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(callsTo('/save')).toHaveLength(1))
    expect(callsTo('/preview')).toHaveLength(0)
    expect(contextRequest).toHaveBeenCalledWith(
      '/save',
      expect.objectContaining({
        edits: [
          expect.objectContaining({
            source_type: 'prompt',
            source_id: 'research',
            expected_revision: 'sha256:research',
            content: 'Updated research policy.',
          }),
        ],
      }),
    )
  })

  it('clears workflow exceptions when a row changes where it is used', async () => {
    const source = {
      ...research,
      policy: { ...research.policy!, workflows: ['security-research'] },
    }
    vi.mocked(contextRequest).mockImplementation(async (path) => {
      if (path.startsWith('/history')) return []
      return { ...inventory, sources: [source] }
    })
    renderPage()
    fireEvent.click(
      await screen.findByRole('button', { name: 'Security Research' }),
    )
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }))
    fireEvent.change(screen.getByLabelText('Used by'), {
      target: { value: 'global' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(callsTo('/save')).toHaveLength(1))
    expect(callsTo('/save')[0][1]).toEqual(
      expect.objectContaining({
        edits: [
          expect.objectContaining({
            source_id: 'research',
            policy: expect.objectContaining({
              scope: 'global',
              targets: [],
              workflows: [],
            }),
          }),
        ],
      }),
    )
  })

  it('keeps a stale draft available after the server rejects Save', async () => {
    vi.mocked(contextRequest).mockImplementation(async (path) => {
      if (path === '/save')
        throw new Error('Source changed. Reload and review the new revision.')
      if (path.startsWith('/history')) return []
      return inventory
    })
    renderPage()
    fireEvent.click(
      await screen.findByRole('button', { name: 'Security Research' }),
    )
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }))
    fireEvent.change(screen.getByLabelText('Content'), {
      target: { value: 'Keep this draft.' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Source changed')
    expect(screen.getByDisplayValue('Keep this draft.')).toBeInTheDocument()
  })

  it('treats project and app selectors as preview controls without saving', async () => {
    renderPage()
    await screen.findByRole('button', { name: 'Security Research' })
    fireEvent.change(screen.getByLabelText('Project'), {
      target: { value: 'agent-hub' },
    })
    fireEvent.change(screen.getByLabelText('App'), {
      target: { value: 'claude_code' },
    })
    await waitFor(() =>
      expect(contextRequest).toHaveBeenCalledWith(
        '/inventory',
        expect.objectContaining({
          project_id: 'agent-hub',
          consumer_surface: 'claude_code',
        }),
      ),
    )
    expect(callsTo('/save')).toHaveLength(0)
    expect(callsTo('/preview')).toHaveLength(0)
  })

  it('hides stale preview and blocks old row edits until the new inventory arrives', async () => {
    let resolveInventory: (value: ContextInventory) => void = () => {}
    vi.mocked(contextRequest).mockImplementation(async (path, payload) => {
      if (
        path === '/inventory' &&
        (payload as { project_id?: string } | undefined)?.project_id ===
          'agent-hub'
      )
        return new Promise<ContextInventory>((resolve) => {
          resolveInventory = resolve
        })
      if (path.startsWith('/history')) return []
      return inventory
    })
    renderPage()
    fireEvent.click(
      await screen.findByRole('button', { name: 'Security Research' }),
    )
    fireEvent.click(screen.getByText('View full preview'))
    expect(
      screen.getByText('Required global rules and ST essentials.'),
    ).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Project'), {
      target: { value: 'agent-hub' },
    })
    expect(await screen.findAllByText('Updating preview…')).not.toHaveLength(0)
    expect(
      screen.queryByText('Required global rules and ST essentials.'),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Edit' }),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole('checkbox', { name: 'Select Security Research' }),
    ).not.toBeInTheDocument()
    expect(callsTo('/save')).toHaveLength(0)
    resolveInventory(inventory)
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Edit' })).toBeEnabled(),
    )
  })

  it('does not include computed sources in editable bulk selections', async () => {
    renderPage()
    await screen.findByRole('button', { name: 'Security Research' })
    expect(
      screen.getByRole('checkbox', { name: 'Select Capabilities' }),
    ).toBeDisabled()
    fireEvent.click(
      screen.getByRole('checkbox', { name: 'Select Security Research' }),
    )
    fireEvent.click(
      screen.getByRole('checkbox', { name: 'Select Operations Guide' }),
    )
    const bulk = screen.getByRole('region', { name: 'Selected items' })
    expect(bulk).toHaveTextContent('2 selected')
    fireEvent.change(within(bulk).getByLabelText('Actions'), {
      target: { value: 'disable' },
    })
    fireEvent.click(within(bulk).getByRole('button', { name: 'Apply' }))
    await waitFor(() => expect(callsTo('/save')).toHaveLength(1))
    const request = callsTo('/save')[0][1]
    expect(request).toEqual(
      expect.objectContaining({
        edits: expect.arrayContaining([
          expect.objectContaining({ source_id: 'research', enabled: false }),
          expect.objectContaining({ source_id: 'operations', enabled: false }),
        ]),
      }),
    )
    expect(callsTo('/preview')).toHaveLength(0)
  })

  it('clears workflow exceptions in a bulk change of where used', async () => {
    const source = {
      ...research,
      policy: { ...research.policy!, workflows: ['security-research'] },
    }
    vi.mocked(contextRequest).mockImplementation(async (path) => {
      if (path.startsWith('/history')) return []
      return { ...inventory, sources: [source] }
    })
    renderPage()
    await screen.findByRole('button', { name: 'Security Research' })
    fireEvent.click(
      screen.getByRole('checkbox', { name: 'Select Security Research' }),
    )
    const bulk = screen.getByRole('region', { name: 'Selected items' })
    fireEvent.change(within(bulk).getByLabelText('Actions'), {
      target: { value: 'scope' },
    })
    expect(bulk).toHaveTextContent('workflow exceptions')
    fireEvent.change(within(bulk).getByLabelText('Used by'), {
      target: { value: 'global' },
    })
    fireEvent.click(within(bulk).getByRole('button', { name: 'Apply' }))
    await waitFor(() => expect(callsTo('/save')).toHaveLength(1))
    expect(callsTo('/save')[0][1]).toEqual(
      expect.objectContaining({
        edits: [
          expect.objectContaining({
            source_id: 'research',
            policy: expect.objectContaining({
              scope: 'global',
              targets: [],
              workflows: [],
            }),
          }),
        ],
      }),
    )
  })

  it('clears bulk selection when a filter hides a selected item', async () => {
    renderPage()
    await screen.findByRole('button', { name: 'Security Research' })
    fireEvent.click(
      screen.getByRole('checkbox', { name: 'Select Security Research' }),
    )
    fireEvent.click(
      screen.getByRole('checkbox', { name: 'Select Operations Guide' }),
    )
    expect(
      screen.getByRole('region', { name: 'Selected items' }),
    ).toHaveTextContent('2 selected')

    fireEvent.change(
      screen.getByLabelText('Search instructions and memories'),
      {
        target: { value: 'Project-specific research policy.' },
      },
    )
    expect(
      screen.queryByRole('button', { name: 'Operations Guide' }),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole('region', { name: 'Selected items' }),
    ).not.toBeInTheDocument()

    fireEvent.click(
      screen.getByRole('checkbox', { name: 'Select Security Research' }),
    )
    const bulk = screen.getByRole('region', { name: 'Selected items' })
    expect(bulk).toHaveTextContent('1 selected')
    fireEvent.change(within(bulk).getByLabelText('Actions'), {
      target: { value: 'disable' },
    })
    fireEvent.click(within(bulk).getByRole('button', { name: 'Apply' }))
    await waitFor(() => expect(callsTo('/save')).toHaveLength(1))
    expect(callsTo('/save')[0][1]).toEqual(
      expect.objectContaining({
        edits: [
          expect.objectContaining({ source_id: 'research', enabled: false }),
        ],
      }),
    )
  })

  it('does not overwrite an unfinished row edit with a bulk action', async () => {
    renderPage()
    fireEvent.click(
      await screen.findByRole('button', { name: 'Security Research' }),
    )
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }))
    fireEvent.change(screen.getByLabelText('Content'), {
      target: { value: 'Keep my unfinished revision.' },
    })
    fireEvent.click(
      screen.getByRole('checkbox', { name: 'Select Security Research' }),
    )
    const bulk = screen.getByRole('region', { name: 'Selected items' })
    fireEvent.change(within(bulk).getByLabelText('Actions'), {
      target: { value: 'disable' },
    })
    fireEvent.click(within(bulk).getByRole('button', { name: 'Apply' }))
    expect(callsTo('/save')).toHaveLength(0)
    expect(bulk).toHaveTextContent(
      'Save or cancel edits to the selected items before applying an action.',
    )
    expect(
      screen.getByDisplayValue('Keep my unfinished revision.'),
    ).toBeInTheDocument()
  })

  it('undoes a recorded change through the source history', async () => {
    vi.mocked(contextRequest).mockImplementation(async (path) => {
      if (path.startsWith('/history'))
        return [
          {
            id: 'change-1',
            kind: 'change',
            actor: 'operator',
            created_at: '2026-09-23T12:00:00Z',
            payload: {
              changes: [
                {
                  before: { source_id: 'research', name: 'Security Research' },
                },
              ],
            },
          },
        ]
      return inventory
    })
    renderPage()
    fireEvent.click(
      await screen.findByRole('button', { name: 'Security Research' }),
    )
    fireEvent.click(screen.getByText('History'))
    fireEvent.click(await screen.findByRole('button', { name: 'Undo' }))
    await waitFor(() =>
      expect(callsTo('/changes/change-1/undo')).toHaveLength(1),
    )
    expect(callsTo('/save')).toHaveLength(0)
  })
})
