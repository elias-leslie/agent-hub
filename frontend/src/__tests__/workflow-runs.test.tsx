import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import WorkflowRunPage from '@/app/workflow-runs/[id]/page'
import WorkflowRunsPage from '@/app/workflow-runs/page'
import { SidebarNav } from '@/components/layout/sidebar-nav'
import { createQueryClientWrapper } from './test-utils'
import {
  attempt,
  CODEX,
  listItem,
  OPUS_48,
  OPUS_55,
  run,
  step,
} from './workflow-runs-fixture'

vi.mock('next/navigation', () => ({
  useParams: () => ({ id: 'r1111111-0000-0000-0000-000000000000' }),
  usePathname: () => '/workflow-runs',
}))

vi.mock('@/lib/api/workflow-runs', async (original) => ({
  ...(await original<typeof import('@/lib/api/workflow-runs')>()),
  fetchWorkflowRuns: vi.fn(),
  fetchWorkflowRun: vi.fn(),
  resumeWorkflowRun: vi.fn(),
}))

import {
  fetchWorkflowRun,
  fetchWorkflowRuns,
  resumeWorkflowRun,
} from '@/lib/api/workflow-runs'

function mount(ui: React.ReactElement) {
  const Wrapper = createQueryClientWrapper()
  return render(<Wrapper>{ui}</Wrapper>)
}

beforeEach(() => {
  vi.mocked(fetchWorkflowRuns).mockReset()
  vi.mocked(fetchWorkflowRun).mockReset()
  vi.mocked(resumeWorkflowRun).mockReset()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('sidebar', () => {
  it('links to workflow runs', () => {
    render(<SidebarNav isCollapsed={false} pathname="/dashboard" />)
    const link = screen
      .getAllByRole('link')
      .find((l) => l.getAttribute('href') === '/workflow-runs')
    expect(link).toBeDefined()
  })
})

describe('workflow runs list', () => {
  it('shows a loading state, then rows with unknown usage as n/a rather than zero', async () => {
    vi.mocked(fetchWorkflowRuns).mockResolvedValue({
      runs: [
        listItem(),
        listItem({
          id: 'r2222222-0000-0000-0000-000000000000',
          state: 'running',
          goal: 'Fresh run',
          step_counts: { pending: 4 },
          attempt_count: 0,
          served_models: [],
          total_tokens: null,
          cost_usd: null,
        }),
      ],
      total: 2,
      limit: 50,
      offset: 0,
    })
    mount(<WorkflowRunsPage />)
    expect(screen.getByLabelText('Loading workflow runs')).toBeInTheDocument()
    const rows = await screen.findAllByTestId('workflow-run-row')
    expect(rows).toHaveLength(2)
    expect(rows[0]).toHaveAttribute(
      'href',
      '/workflow-runs/r1111111-0000-0000-0000-000000000000',
    )
    expect(within(rows[0]).getByText('4 of 4 done')).toBeInTheDocument()
    expect(within(rows[0]).getByText('Opus 5.5')).toBeInTheDocument()
    expect(within(rows[1]).getByText('no attempts yet')).toBeInTheDocument()
    expect(within(rows[1]).getByText('tokens n/a')).toBeInTheDocument()
    expect(within(rows[1]).getByText('cost n/a')).toBeInTheDocument()
    expect(screen.getByTestId('workflow-runs-total')).toHaveTextContent(
      '2 runs',
    )
  })

  it('says so when there are no runs, and when the request fails', async () => {
    vi.mocked(fetchWorkflowRuns).mockResolvedValueOnce({
      runs: [],
      total: 0,
      limit: 50,
      offset: 0,
    })
    const first = mount(<WorkflowRunsPage />)
    expect(await screen.findByText('No workflow runs yet.')).toBeInTheDocument()
    first.unmount()

    vi.mocked(fetchWorkflowRuns).mockRejectedValue(
      new Error('Workflow runs request failed (500)'),
    )
    mount(<WorkflowRunsPage />)
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Could not load workflow runs',
    )
    expect(screen.queryByText('No workflow runs yet.')).not.toBeInTheDocument()
  })

  it('flags attempts that were refused or substituted', async () => {
    vi.mocked(fetchWorkflowRuns).mockResolvedValue({
      runs: [
        listItem({ flagged_attempts: 2, served_models: [CODEX, OPUS_48] }),
      ],
      total: 1,
      limit: 50,
      offset: 0,
    })
    mount(<WorkflowRunsPage />)
    expect(await screen.findByText('2 flagged')).toBeInTheDocument()
  })
})

describe('workflow run detail', () => {
  it('makes a substitution unmistakable and shows the handoff and session link', async () => {
    vi.mocked(fetchWorkflowRun).mockResolvedValue(
      run({
        steps: [
          step({
            attempt_history: [
              attempt({
                served_models: [OPUS_48],
                served_model: OPUS_48,
                outcome: {
                  kind: 'substituted',
                  requested_model: OPUS_55,
                  served_model: OPUS_48,
                  category: 'cyber',
                },
              }),
            ],
          }),
        ],
      }),
    )
    mount(<WorkflowRunPage />)
    const note = await screen.findByText(/Substituted:/)
    const callout = note.closest('[role="note"]') as HTMLElement
    expect(callout).toHaveTextContent(
      'Substituted: asked Opus 5.5, answered by Opus 4.8',
    )
    expect(callout).toHaveTextContent('switched models (cyber)')
    expect(screen.getByTestId('attempt')).toHaveAttribute(
      'data-substituted',
      'true',
    )
    expect(
      screen.getByText('Planned the export change in two files.'),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('link', { name: 'Open attempt session' }),
    ).toHaveAttribute(
      'href',
      '/sessions?sel=a1111111-0000-0000-0000-000000000000',
    )
    expect(screen.getByTestId('attempt')).toHaveTextContent(
      '42.0s · 1.2K tok · $0.012',
    )
  })

  it('shows a refusal with its category, then the takeover by the next model', async () => {
    vi.mocked(fetchWorkflowRun).mockResolvedValue(
      run({
        steps: [
          step({
            attempt_history: [
              attempt({
                status: 'failed',
                outcome: {
                  kind: 'refused',
                  requested_model: OPUS_55,
                  category: 'cyber',
                  explanation: 'Declined the request.',
                },
                error: 'refused',
                next_hop: {
                  from_model: OPUS_55,
                  to_model: CODEX,
                  category: 'cyber',
                  kind: 'refused',
                },
              }),
              attempt({
                session_id: 'a2222222-0000-0000-0000-000000000000',
                attempt: 2,
                requested_model: OPUS_55,
                effective_model: CODEX,
                served_model: CODEX,
                served_models: [CODEX],
                executor: 'codex',
                hop_from: {
                  from_model: OPUS_55,
                  to_model: CODEX,
                  category: 'cyber',
                  kind: 'refused',
                },
                usage: null,
              }),
            ],
          }),
        ],
      }),
    )
    mount(<WorkflowRunPage />)
    const attempts = await screen.findAllByTestId('attempt')
    expect(attempts[0]).toHaveTextContent(
      'Refused (cyber). Declined the request.',
    )
    expect(attempts[0]).toHaveTextContent(`Moved on to ${CODEX}`)
    expect(attempts[1]).toHaveTextContent(
      'Took over from Opus 5.5 after refused (cyber)',
    )
    expect(attempts[1]).toHaveTextContent('Codex')
    expect(attempts[1]).toHaveTextContent('tokens n/a')
    expect(attempts[1]).not.toHaveAttribute('data-substituted')
  })

  it('shows a usage limit with its reset time', async () => {
    const resets = 1_900_000_000
    vi.mocked(fetchWorkflowRun).mockResolvedValue(
      run({
        steps: [
          step({
            status: 'failed',
            attempt_history: [
              attempt({
                status: 'failed',
                outcome: {
                  kind: 'usage_limit',
                  requested_model: OPUS_55,
                  window: 'five_hour',
                  resets_at: resets,
                },
                error: 'usage limit',
              }),
            ],
          }),
        ],
      }),
    )
    mount(<WorkflowRunPage />)
    const text = (await screen.findByText(/Usage limit reached/)).closest(
      '[role="note"]',
    )
    expect(text).toHaveTextContent('Usage limit reached (five hour).')
    expect(text).toHaveTextContent(
      `Resets ${new Date(resets * 1000).toLocaleString()}`,
    )
  })

  it('shows attempts against their caps and the acceptance checks the runner ran', async () => {
    vi.mocked(fetchWorkflowRun).mockResolvedValue(
      run({
        steps: [
          step({
            status: 'failed',
            attempts: 3,
            attempt_limit: 3,
            acceptance: [{ cmd: 'make test', timeout_s: null }],
            acceptance_failures: 2,
            usage_limit_resumes: 1,
            restarts: 1,
            effort: 'low',
            attempt_history: [
              attempt({
                status: 'failed',
                decision: { action: 'retry', reason: 'acceptance_failed' },
                acceptance: [
                  {
                    cmd: 'make test',
                    exit_code: 2,
                    timed_out: false,
                    duration_s: 1.5,
                    output_tail: 'FAILED test_export',
                    passed: false,
                  },
                ],
              }),
            ],
          }),
        ],
      }),
    )
    mount(<WorkflowRunPage />)
    const limits = await screen.findByTestId('step-limits')
    expect(limits).toHaveTextContent(
      'Attempt 3 of 3 · acceptance retries 2 of 2 · usage-limit resumes 1 of 3 · restarts 1 of 2 · effort low',
    )
    expect(screen.getByTestId('run-limits')).toHaveTextContent(
      '12 attempts · 3 usage-limit resumes · 2 acceptance retries · 2 restarts',
    )
    const checks = screen.getByTestId('acceptance')
    expect(checks).toHaveTextContent('Failed (exit 2)')
    expect(checks).toHaveTextContent('make test')
    expect(checks).toHaveTextContent('FAILED test_export')
  })

  it('shows the plain attempt count when the run reports no limits', async () => {
    vi.mocked(fetchWorkflowRun).mockResolvedValue(
      run({
        limits: undefined,
        steps: [step({ attempt_limit: undefined, attempts: 2 })],
      }),
    )
    mount(<WorkflowRunPage />)
    expect(await screen.findByTestId('step-limits')).toHaveTextContent(
      'Attempt 2',
    )
    expect(screen.queryByTestId('run-limits')).toBeNull()
  })

  it('explains a paused run and sends the owner decision', async () => {
    vi.mocked(fetchWorkflowRun).mockResolvedValue(
      run({
        state: 'needs_owner',
        pause: { reason: 'chain_exhausted', step_key: 'plan' },
        steps: [step({ status: 'needs_owner' })],
      }),
    )
    vi.mocked(resumeWorkflowRun).mockResolvedValue({
      run_id: 'r1',
      state: 'running',
      step: 'plan',
      status: 'pending',
    })
    mount(<WorkflowRunPage />)
    const panel = await screen.findByRole('region', { name: 'Waiting for you' })
    expect(panel).toHaveTextContent('every model in its chain was tried')

    fireEvent.change(within(panel).getByLabelText('Retry on'), {
      target: { value: CODEX },
    })
    fireEvent.click(within(panel).getByRole('button', { name: 'Retry step' }))
    await waitFor(() =>
      expect(resumeWorkflowRun).toHaveBeenCalledWith(
        'r1111111-0000-0000-0000-000000000000',
        {
          action: 'retry',
          step_key: 'plan',
          model: CODEX,
        },
      ),
    )

    // Ending the run needs a second click.
    fireEvent.click(within(panel).getByRole('button', { name: 'End run' }))
    expect(resumeWorkflowRun).toHaveBeenCalledTimes(1)
    fireEvent.click(
      within(panel).getByRole('button', { name: 'Confirm: end run as failed' }),
    )
    await waitFor(() =>
      expect(resumeWorkflowRun).toHaveBeenLastCalledWith(expect.any(String), {
        action: 'fail',
        step_key: 'plan',
        model: undefined,
      }),
    )
  })

  it('keeps the run on screen and says it is stale when a refresh fails', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.mocked(fetchWorkflowRun)
      .mockResolvedValueOnce(
        run({ state: 'running', steps: [step({ status: 'running' })] }),
      )
      .mockRejectedValue(new Error('Workflow run request failed (503)'))
    mount(<WorkflowRunPage />)
    expect(
      await screen.findByText('Add CSV export to the reports page'),
    ).toBeInTheDocument()
    await act(() => vi.advanceTimersByTimeAsync(3100))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Could not refresh this run')
    expect(alert).toHaveTextContent('may be out of date')
    expect(
      screen.getByText('Add CSV export to the reports page'),
    ).toBeInTheDocument()
  })

  it('polls while running and stops once the run has finished', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.mocked(fetchWorkflowRun)
      .mockResolvedValueOnce(
        run({
          state: 'running',
          steps: [step({ status: 'running', attempt_history: [] })],
        }),
      )
      .mockResolvedValue(run({ state: 'completed' }))
    mount(<WorkflowRunPage />)
    expect(await screen.findByText(/Live, refreshing/)).toBeInTheDocument()
    expect(fetchWorkflowRun).toHaveBeenCalledTimes(1)

    await act(() => vi.advanceTimersByTimeAsync(3100))
    await waitFor(() => expect(fetchWorkflowRun).toHaveBeenCalledTimes(2))
    await waitFor(() =>
      expect(screen.queryByText(/Live, refreshing/)).not.toBeInTheDocument(),
    )

    await act(() => vi.advanceTimersByTimeAsync(30_000))
    expect(fetchWorkflowRun).toHaveBeenCalledTimes(2)
  })

  it('says when the run does not exist', async () => {
    vi.mocked(fetchWorkflowRun).mockRejectedValue(
      new Error('Run not found (404)'),
    )
    mount(<WorkflowRunPage />)
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Run not found (404)',
    )
  })
})
