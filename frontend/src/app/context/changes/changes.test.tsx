import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  fetchChanges,
  fetchDecisions,
  keepChanges,
  type Queue,
  type QueueRow,
  ReviewError,
  refuseChanges,
} from '@/lib/api/context-changes'
import { collapse } from './components/DiffView'
import { lineDiff, rowDiff } from './diff'
import ContextChangesPage from './page'
import { groupRows } from './present'

vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => '/context/changes',
  useSearchParams: () => new URLSearchParams(),
}))
vi.mock('@/lib/api/sessions', () => ({
  fetchSessionFacets: vi
    .fn()
    .mockResolvedValue({ projects: [], work_roles: [] }),
}))
vi.mock('@/lib/api/context-changes', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/api/context-changes')>()),
  fetchChanges: vi.fn(),
  fetchDecisions: vi.fn(),
  keepChanges: vi.fn(),
  refuseChanges: vi.fn(),
  reworkChange: vi.fn(),
  fetchMemoryTitles: vi.fn().mockResolvedValue({}),
}))

const row = (o: Partial<QueueRow> & { key: string }): QueueRow => ({
  target_kind: 'memory',
  target_id: o.key.split(':')[1],
  title: o.key,
  change: 'update',
  actions: ['update'],
  first_at: '2026-11-01T10:00:00Z',
  last_at: '2026-11-01T10:00:00Z',
  base_revision: 'b',
  through_revision: 'r1',
  version: 2,
  scope_before: 'global reference',
  scope_after: 'global reference',
  before: { content: 'a', tokens: 1 },
  after: { content: 'a\nb', tokens: 2 },
  delta_tokens: 1,
  tokens_per_day: null,
  reach: null,
  also_undoes: [],
  writers: [
    {
      kind: 'agent',
      session: 'aico-widget-aaaa1111',
      delivery: null,
      harness: 'claude',
      work_role: 'implementation',
      project: null,
      coordinator: false,
      resolved: true,
    },
  ],
  sessions: ['aico-widget-aaaa1111'],
  linked: [],
  hint: null,
  ...o,
})

const queue = (
  rows: QueueRow[],
  automatic: Queue['automatic'] = [],
): Queue => ({
  rows,
  summary: {
    count: rows.length,
    by_kind: {},
    global_count: 0,
    tokens_per_day: 0,
    unknown_reach: rows.filter((r) => !r.reach).length,
  },
  automatic,
})

const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider
    client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
  >
    {children}
  </QueryClientProvider>
)

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(fetchDecisions).mockResolvedValue([])
})

describe('diff', () => {
  it('marks added and removed lines and folds long unchanged runs', () => {
    const d = lineDiff('a\nb\nc\nd\ne\nf\ng\nh', 'a\nb\nc\nd\nX\nf\ng\nh')
    expect(d.filter((l) => l.type !== 'same')).toEqual([
      { type: 'del', text: 'e' },
      { type: 'add', text: 'X' },
    ])
    expect(collapse(d, 1).some((l) => l.type === 'gap')).toBe(true)
  })

  it('reports field changes and treats a create as all added', () => {
    const diff = rowDiff({
      before: { scope: 'global', content: '' },
      after: { scope: 'project', content: 'x\ny' },
    })
    expect(diff.fields).toEqual([
      { field: 'scope', label: 'Scope', before: 'global', after: 'project' },
    ])
    expect(diff.added).toBe(2)
    expect(rowDiff({ before: null, after: { content: 'x' } }).added).toBe(1)
  })
})

describe('grouping', () => {
  it('groups rows of one session and leaves single and sessionless rows alone', () => {
    const rows = [
      row({ key: 'memory:1' }),
      row({ key: 'memory:2' }),
      row({ key: 'memory:3', sessions: ['other'] }),
      row({ key: 'memory:4', sessions: [] }),
    ]
    const { groups, singles } = groupRows(rows)
    expect(groups.map((g) => g.rows.length)).toEqual([2])
    expect(singles.map((r) => r.key)).toEqual(['memory:3', 'memory:4'])
  })
})

describe('Changes page', () => {
  it('shows unknown reach as an em dash and keeps automatic changes out of the waiting count', async () => {
    vi.mocked(fetchChanges).mockResolvedValue(
      queue(
        [row({ key: 'memory:1', title: 'One' })],
        [
          {
            key: 'memory:9',
            target_kind: 'memory',
            target_id: '9',
            title: 'Retired note',
            action: 'delete',
            at: '2026-11-01T09:00:00Z',
            revision: 'x',
            by: 'retirement',
            reason: null,
          },
        ],
      ),
    )
    render(<ContextChangesPage />, { wrapper })
    const item = (await screen.findByText('One')).closest('li') as HTMLElement
    expect(within(item).getByText('(not known yet)')).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /^Unreviewed/ }),
    ).toHaveTextContent('1')
    expect(screen.getByText(/not waiting for review/)).toBeInTheDocument()
  })

  it('warns inline on refuse when owner edits would be undone', async () => {
    vi.mocked(fetchChanges).mockResolvedValue(
      queue([
        row({
          key: 'memory:1',
          title: 'One',
          also_undoes: [
            {
              revision: 'o',
              at: '2026-11-01T10:30:00Z',
              writer_kind: 'owner',
              action: 'update',
              by: 'owner',
            },
          ],
        }),
      ]),
    )
    render(<ContextChangesPage />, { wrapper })
    expect(await screen.findByTestId('also-undoes')).toHaveTextContent(
      '1 later edit of yours',
    )
  })

  it('on 409 says it changed, reloads, and keeps a row the server no longer lists in view', async () => {
    const one = row({ key: 'memory:1', title: 'One' })
    vi.mocked(fetchChanges)
      .mockResolvedValueOnce(queue([one]))
      .mockResolvedValue(queue([]))
    vi.mocked(keepChanges).mockRejectedValue(
      new ReviewError(409, 'changed', 'memory:1'),
    )
    render(<ContextChangesPage />, { wrapper })
    fireEvent.click(await screen.findByRole('button', { name: 'Keep One' }))
    expect(
      await screen.findByText(
        /Changed since you loaded it, and it is no longer waiting here/,
      ),
    ).toBeInTheDocument()
    expect(screen.getByText('One')).toBeInTheDocument()
    expect(fetchChanges).toHaveBeenCalledTimes(2)
  })

  it('on 409 for a row still waiting, reloads and shows the new diff', async () => {
    vi.mocked(fetchChanges)
      .mockResolvedValueOnce(queue([row({ key: 'memory:1', title: 'One' })]))
      .mockResolvedValue(
        queue([
          row({
            key: 'memory:1',
            title: 'One',
            through_revision: 'r2',
            after: { content: 'a\nb\nc', tokens: 3 },
          }),
        ]),
      )
    vi.mocked(refuseChanges).mockRejectedValue(
      new ReviewError(409, 'changed', 'memory:1'),
    )
    render(<ContextChangesPage />, { wrapper })
    fireEvent.click(await screen.findByRole('button', { name: 'Refuse One' }))
    expect(
      await screen.findByText(/Changed since you loaded it\. Reloaded/),
    ).toBeInTheDocument()
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Keep One' })).toBeEnabled(),
    )
  })

  it('explains a 422 in plain words and leaves the row', async () => {
    vi.mocked(fetchChanges).mockResolvedValue(
      queue([row({ key: 'memory:1', title: 'One' })]),
    )
    vi.mocked(keepChanges).mockRejectedValue(
      new ReviewError(422, 'x is not a registered project'),
    )
    render(<ContextChangesPage />, { wrapper })
    fireEvent.click(await screen.findByRole('button', { name: 'Keep One' }))
    expect(
      await screen.findByText('Not saved: x is not a registered project'),
    ).toBeInTheDocument()
    expect(screen.getByText('One')).toBeInTheDocument()
  })

  it('Keep all sends the whole session in one request', async () => {
    vi.mocked(fetchChanges).mockResolvedValue(
      queue([
        row({ key: 'memory:1', title: 'One' }),
        row({ key: 'memory:2', title: 'Two' }),
      ]),
    )
    vi.mocked(keepChanges).mockResolvedValue({
      results: [],
      linked_pending: [],
    })
    render(<ContextChangesPage />, { wrapper })
    fireEvent.click(await screen.findByRole('button', { name: 'Keep all (2)' }))
    expect(keepChanges).toHaveBeenCalledWith([
      expect.objectContaining({
        target_id: '1',
        through_revision: 'r1',
        expected_version: 2,
      }),
      expect.objectContaining({ target_id: '2' }),
    ])
  })

  it('says when loading fails instead of showing an empty list', async () => {
    vi.mocked(fetchChanges).mockRejectedValue(
      new Error('Loading changes failed: 500'),
    )
    render(<ContextChangesPage />, { wrapper })
    expect(
      await screen.findByRole('alert', {}, { timeout: 4000 }),
    ).toHaveTextContent("Couldn't load the changes")
    expect(screen.queryByText(/Nothing waiting/)).not.toBeInTheDocument()
  })
})
