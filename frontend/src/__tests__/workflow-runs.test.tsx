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
  costTotals,
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
  cancelWorkflowRun: vi.fn(),
  cancelWorkflowStep: vi.fn(),
}))

import {
  cancelWorkflowRun,
  cancelWorkflowStep,
  fetchWorkflowRun,
  fetchWorkflowRuns,
  resumeWorkflowRun,
} from '@/lib/api/workflow-runs'

const CANCEL = {
  scope: 'run' as const,
  reason: 'wrong branch',
  requested_by: 'owner',
  requested_at: 1_793_181_000,
}

function mount(ui: React.ReactElement) {
  const Wrapper = createQueryClientWrapper()
  return render(<Wrapper>{ui}</Wrapper>)
}

beforeEach(() => {
  vi.mocked(fetchWorkflowRuns).mockReset()
  vi.mocked(fetchWorkflowRun).mockReset()
  vi.mocked(resumeWorkflowRun).mockReset()
  vi.mocked(cancelWorkflowRun).mockReset()
  vi.mocked(cancelWorkflowStep).mockReset()
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
          cost: costTotals(),
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
    expect(
      within(rows[0]).getByText('$0.060 subscription equiv.'),
    ).toBeInTheDocument()
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
  it('shows the run total split by basis, with unpriced attempts apart, and each attempt cost with its basis', async () => {
    vi.mocked(fetchWorkflowRun).mockResolvedValue(
      run({
        usage_totals: {
          total_tokens: 3000,
          cost: costTotals({ metered: 0.01, subscription_equiv: 0.5 }, 1),
        },
        steps: [
          step({
            attempt_history: [
              attempt({
                usage: {
                  total_tokens: 1000,
                  cost_usd: 0.01,
                  cost_basis: 'metered',
                  cost_source: 'provider_reported',
                },
              }),
            ],
          }),
        ],
      }),
    )
    mount(<WorkflowRunPage />)
    expect(await screen.findByTestId('run-cost')).toHaveTextContent(
      '$0.010 metered · $0.500 subscription equiv. · 1 unpriced',
    )
    expect(screen.getByTestId('attempt')).toHaveTextContent('$0.010 metered')
  })

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
      'Attempt 3 of 3 · acceptance retries 2 of 2 · usage-limit resumes 1, idle in a row 1 of 3 · restarts 1 of 2 · effort low',
    )
    expect(screen.getByTestId('run-limits')).toHaveTextContent(
      '12 attempts · 3 idle usage-limit resumes · 2 acceptance retries · 2 restarts',
    )
    const checks = screen.getByTestId('acceptance')
    expect(checks).toHaveTextContent('Failed (exit 2)')
    expect(checks).toHaveTextContent('make test')
    expect(checks).toHaveTextContent('FAILED test_export')
  })

  it('shows the phase, last activity and process state next to a running step', async () => {
    const at = (secondsAgo: number) =>
      new Date(Date.now() - secondsAgo * 1000).toISOString()
    vi.mocked(fetchWorkflowRun).mockResolvedValue(
      run({
        state: 'running',
        steps: [
          step({
            status: 'running',
            live: {
              phase: 'tool:Bash',
              last_event_at: at(12),
              harness_pid: 4242,
              harness_alive: true,
              updated_at: at(5),
            },
          }),
        ],
      }),
    )
    mount(<WorkflowRunPage />)
    const live = await screen.findByTestId('step-live')
    expect(live).toHaveTextContent(
      'Running tool Bash · last activity 12s ago · process alive',
    )
    expect(live).toHaveAttribute('data-phase', 'tool:Bash')
  })

  it('says a running step has no live status or a missing process rather than calling it idle', async () => {
    const old = new Date(Date.now() - 600_000).toISOString()
    vi.mocked(fetchWorkflowRun).mockResolvedValue(
      run({
        state: 'running',
        steps: [
          step({ key: 'a', status: 'running', live: null }),
          step({
            key: 'b',
            position: 1,
            status: 'running',
            live: {
              phase: 'thinking',
              last_event_at: null,
              harness_pid: 77,
              harness_alive: false,
              updated_at: old,
            },
          }),
        ],
      }),
    )
    mount(<WorkflowRunPage />)
    const [first, second] = await screen.findAllByTestId('step-live')
    expect(first).toHaveTextContent(
      'no live status reported yet · process state unknown',
    )
    expect(second).toHaveTextContent(
      'Thinking · no activity seen yet · process not found · status saved 10m ago',
    )
  })

  it('shows the attempts the owner added and offers to add more at the cap', async () => {
    vi.mocked(fetchWorkflowRun).mockResolvedValue(
      run({
        state: 'needs_owner',
        pause: { reason: 'usage_limit_resume_limit', step_key: 'plan' },
        steps: [
          step({
            status: 'needs_owner',
            attempts: 6,
            attempt_limit: 6,
            extra_attempts: {
              total: 2,
              grants: [
                {
                  count: 2,
                  requested_by: 'client-7',
                  request_source: 'dashboard',
                  requested_at: 1_793_181_000,
                  note: null,
                },
              ],
            },
          }),
        ],
      }),
    )
    vi.mocked(resumeWorkflowRun).mockResolvedValue({
      run_id: 'r1',
      state: 'running',
      step: 'plan',
      status: 'pending',
    })
    mount(<WorkflowRunPage />)
    expect(await screen.findByTestId('step-limits')).toHaveTextContent(
      '+2 attempts you added (client-7)',
    )
    const panel = screen.getByRole('region', { name: 'Waiting for you' })
    fireEvent.change(within(panel).getByLabelText(/Add attempts/), {
      target: { value: '3' },
    })
    fireEvent.click(within(panel).getByRole('button', { name: 'Retry step' }))
    await waitFor(() =>
      expect(resumeWorkflowRun).toHaveBeenCalledWith(expect.any(String), {
        action: 'retry',
        step_key: 'plan',
        model: undefined,
        extra_attempts: 3,
      }),
    )
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

  it('shows the tools an attempt got and why a tier-limited step is paused', async () => {
    vi.mocked(fetchWorkflowRun).mockResolvedValue(
      run({
        state: 'needs_owner',
        pause: {
          reason: 'tools_unavailable',
          step_key: 'plan',
          error:
            "tools_unavailable: project tier 'read' allows only [read_file]",
        },
        steps: [
          step({
            status: 'needs_owner',
            attempt_history: [
              attempt({
                status: 'failed',
                tools: ['read_file'],
                error:
                  "tools_unavailable: project tier 'read' allows only [read_file]",
              }),
            ],
          }),
        ],
      }),
    )
    mount(<WorkflowRunPage />)
    const panel = await screen.findByRole('region', { name: 'Waiting for you' })
    expect(panel).toHaveTextContent(
      "project tier 'read' allows only [read_file]",
    )
    expect(await screen.findByTestId('attempt-tools')).toHaveTextContent(
      'Tools: read_file',
    )
  })

  it('names the other steps that also wait for the owner', async () => {
    vi.mocked(fetchWorkflowRun).mockResolvedValue(
      run({
        state: 'needs_owner',
        pause: {
          reason: 'chain_exhausted',
          step_key: 'plan',
          waiting: {
            plan: { reason: 'chain_exhausted' },
            build: { reason: 'chain_exhausted' },
          },
        },
        steps: [step({ status: 'needs_owner' })],
      }),
    )
    mount(<WorkflowRunPage />)
    const panel = await screen.findByRole('region', { name: 'Waiting for you' })
    expect(panel).toHaveTextContent('Also waiting for you: build.')
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

  it('says a run waits because a step failed, what finished and what is blocked, and sends skip for the failed step', async () => {
    vi.mocked(fetchWorkflowRun).mockResolvedValue(
      run({
        state: 'needs_owner',
        failure: null,
        pause: {
          reason: 'step_failed',
          step_key: 'a',
          failed: {
            a: {
              status: 'failed',
              reason: 'acceptance_retry_limit',
              error: null,
            },
          },
          blocked: {
            c: {
              state: 'blocked',
              waiting_on: [],
              blocked_by: [{ key: 'a', status: 'failed' }],
              because: [{ key: 'a', status: 'failed' }],
              reason: 'blocked by a (failed)',
            },
          },
        },
        steps: [
          step({
            key: 'a',
            position: 0,
            status: 'failed',
            checkpoint_sha: null,
          }),
          step({ key: 'b', position: 1, status: 'completed' }),
          step({
            key: 'c',
            position: 2,
            status: 'pending',
            attempts: 0,
            attempt_history: [],
            handoff: null,
          }),
        ],
      }),
    )
    vi.mocked(resumeWorkflowRun).mockResolvedValue({
      run_id: 'r1',
      state: 'running',
      step: 'a',
      status: 'skipped',
    })
    mount(<WorkflowRunPage />)
    const panel = await screen.findByRole('region', { name: 'Waiting for you' })
    expect(panel).toHaveTextContent('Step a failed.')
    expect(panel).toHaveTextContent('c cannot start')
    const list = within(panel).getByTestId('pause-failed')
    expect(list).toHaveTextContent('a: failed (acceptance_retry_limit)')
    expect(list).toHaveTextContent('c: blocked by a (failed)')
    fireEvent.click(within(panel).getByRole('button', { name: 'Skip step' }))
    await waitFor(() =>
      expect(resumeWorkflowRun).toHaveBeenCalledWith(
        'r1111111-0000-0000-0000-000000000000',
        { action: 'skip', step_key: 'a', model: undefined },
      ),
    )
  })

  it("shows who launched the run, each step's dependencies, which are ready and why one is blocked", async () => {
    vi.mocked(fetchWorkflowRun).mockResolvedValue(
      run({
        state: 'running',
        launched_by: 'aico-session-7',
        coordinator: 'claude-code',
        plan_revision: 2,
        steps: [
          step({ key: 'a', position: 0, depends_on: [] }),
          step({
            key: 'b',
            position: 1,
            status: 'pending',
            attempts: 0,
            attempt_history: [],
            handoff: null,
            depends_on: ['a'],
            depends_on_explicit: true,
            readiness: {
              state: 'ready',
              waiting_on: [],
              blocked_by: [],
              reason: null,
            },
          }),
          step({
            key: 'c',
            position: 2,
            status: 'pending',
            attempts: 0,
            attempt_history: [],
            handoff: null,
            depends_on: ['b'],
            depends_on_explicit: false,
            readiness: {
              state: 'waiting',
              waiting_on: ['b'],
              blocked_by: [],
              reason: 'waiting for b',
            },
          }),
          step({
            key: 'd',
            position: 3,
            status: 'pending',
            attempts: 0,
            attempt_history: [],
            handoff: null,
            depends_on: ['x'],
            depends_on_explicit: true,
            readiness: {
              state: 'blocked',
              waiting_on: [],
              blocked_by: [{ key: 'x', status: 'skipped' }],
              reason: 'blocked by x (skipped)',
            },
          }),
        ],
      }),
    )
    mount(<WorkflowRunPage />)
    expect(await screen.findByTestId('run-origin')).toHaveTextContent(
      'Launched by aico-session-7 (claude-code) · plan revision 2',
    )
    const [a, b, c, d] = await screen.findAllByTestId('step-deps')
    expect(a).toHaveTextContent('Depends on nothing')
    expect(a).toHaveAttribute('data-readiness', 'started')
    expect(b).toHaveTextContent('Depends on a · Ready to start')
    expect(c).toHaveTextContent('Follows b · Not ready: waiting for b')
    expect(d).toHaveTextContent(
      'Depends on x · Blocked: blocked by x (skipped)',
    )
    expect(d).toHaveAttribute('data-readiness', 'blocked')
  })

  it('lists plan revisions newest first with who changed what', async () => {
    vi.mocked(fetchWorkflowRun).mockResolvedValue(
      run({
        plan_revision: 2,
        plan_history: [
          {
            revision: 1,
            at: 1_793_181_000,
            action: 'add_steps',
            by: { changed_by: 'aico-1', client_id: 'summitflow' },
            reason: 'found more work',
            changes: [
              {
                step: 'extra',
                op: 'add',
                before: null,
                after: { key: 'extra' },
              },
            ],
          },
          {
            revision: 2,
            at: 1_793_181_100,
            action: 'revise_step',
            by: { client_id: 'summitflow' },
            changes: [
              {
                step: 'b',
                op: 'revise',
                before: { model_override: null },
                after: { model_override: 'agent_hub/deepseek' },
              },
            ],
          },
        ],
      }),
    )
    mount(<WorkflowRunPage />)
    const history = await screen.findByTestId('plan-history')
    expect(history).toHaveTextContent('Plan history (2 revisions)')
    const items = within(
      within(history).getByRole('list', { name: 'Plan history' }),
    ).getAllByRole('listitem', { name: '' })
    expect(items[0]).toHaveTextContent('r2 Changed a step by summitflow')
    expect(items[0]).toHaveTextContent(
      'b: model_override none -> agent_hub/deepseek',
    )
    expect(history).toHaveTextContent('r1 Added steps by aico-1')
    expect(history).toHaveTextContent('found more work')
    expect(history).toHaveTextContent('added extra')
  })

  it('shows which steps run at once, their worktrees, branches and merges, and where the final code is', async () => {
    const lane = (key: string, extra: Record<string, unknown> = {}) => ({
      kind: 'lane' as const,
      lane: key,
      worktree: `/srv/runs/r1/lanes/${key}`,
      branch: `workflow/r1111111-${key}`,
      base_sha: 'aaaaaaaa11111111',
      start_sha: 'aaaaaaaa11111111',
      merge_result: 'none' as const,
      merges: [],
      conflict_files: [],
      ...extra,
    })
    vi.mocked(fetchWorkflowRun).mockResolvedValue(
      run({
        state: 'running',
        max_concurrent_steps: 2,
        running_steps: ['a', 'b'],
        uses_lanes: true,
        result: null,
        steps: [
          step({
            key: 'a',
            position: 0,
            status: 'running',
            workspace: lane('a'),
          }),
          step({
            key: 'b',
            position: 1,
            status: 'running',
            workspace: lane('b'),
          }),
          step({
            key: 'join',
            position: 2,
            status: 'pending',
            attempts: 0,
            attempt_history: [],
            handoff: null,
            workspace: lane('join', {
              start_sha: null,
              merge_result: 'conflict',
              conflict_files: ['shared.txt'],
              merges: [
                {
                  step: 'b',
                  sha: 'bbbbbbbb',
                  result: 'conflict',
                  files: ['shared.txt'],
                },
              ],
            }),
          }),
        ],
      }),
    )
    mount(<WorkflowRunPage />)
    expect(await screen.findByTestId('run-concurrency')).toHaveTextContent(
      '2 of 2 steps running: a, b · each step has its own worktree and branch',
    )
    expect(screen.queryByTestId('run-result')).toBeNull()
    const [a, b, join] = await screen.findAllByTestId('step-workspace')
    expect(a).toHaveTextContent(
      'Lane workflow/r1111111-a at /srv/runs/r1/lanes/a',
    )
    expect(a).toHaveTextContent('base aaaaaaaa · start aaaaaaaa')
    expect(b).toHaveTextContent('workflow/r1111111-b')
    expect(join).toHaveAttribute('data-merge', 'conflict')
    expect(join).toHaveTextContent(
      'Merge conflict in shared.txt; this step resolves it first',
    )
    expect(join).not.toHaveTextContent('start ')
  })

  it('says where the final code is once a lane run completes, and when branches could not be merged', async () => {
    vi.mocked(fetchWorkflowRun).mockResolvedValue(
      run({
        max_concurrent_steps: 2,
        running_steps: [],
        uses_lanes: true,
        result: {
          mode: 'lanes',
          state: 'conflict',
          branch: 'workflow/r1111111',
          worktree: '/srv/runs/r1/worktree',
          sha: 'cccccccc99999999',
          merged: ['a'],
          not_merged: ['b'],
          conflict_files: ['shared.txt'],
        },
        steps: [
          step({
            workspace: {
              kind: 'lane',
              lane: 'a',
              worktree: '/srv/runs/r1/lanes/a',
              branch: 'workflow/r1111111-a',
              base_sha: 'aaaaaaaa11111111',
              start_sha: 'aaaaaaaa11111111',
              merge_result: 'clean',
              merges: [
                { step: 'x', sha: 'xxxxxxxx', result: 'clean', files: [] },
              ],
              retired: true,
            },
          }),
        ],
      }),
    )
    mount(<WorkflowRunPage />)
    expect(await screen.findByTestId('run-result')).toHaveTextContent(
      'Branches b could not be merged (conflict in shared.txt); the rest is on workflow/r1111111 at cccccccc',
    )
    expect(screen.getByTestId('run-concurrency')).toHaveTextContent(
      '0 of 2 steps running',
    )
    const ws = screen.getByTestId('step-workspace')
    expect(ws).toHaveTextContent('directory removed, branch kept')
    expect(ws).toHaveTextContent('Clean merge of x')
  })

  it('lists a change to the run itself in the plan history', async () => {
    vi.mocked(fetchWorkflowRun).mockResolvedValue(
      run({
        plan_revision: 1,
        plan_history: [
          {
            revision: 1,
            at: 1_793_181_000,
            action: 'revise_run',
            by: { client_id: 'summitflow' },
            changes: [
              {
                step: null,
                op: 'revise',
                before: { max_concurrent_steps: 1 },
                after: { max_concurrent_steps: 3 },
              },
            ],
          },
        ],
      }),
    )
    mount(<WorkflowRunPage />)
    const history = await screen.findByTestId('plan-history')
    expect(history).toHaveTextContent('r1 Changed the run by summitflow')
    expect(history).toHaveTextContent('run: max_concurrent_steps 1 -> 3')
  })

  it('explains a run blocked on dependencies without offering step decisions', async () => {
    vi.mocked(fetchWorkflowRun).mockResolvedValue(
      run({
        state: 'needs_owner',
        pause: {
          reason: 'blocked_dependencies',
          step_key: 'b',
          blocked: {
            b: {
              state: 'blocked',
              waiting_on: [],
              blocked_by: [{ key: 'a', status: 'skipped' }],
              reason: 'blocked by a (skipped)',
            },
          },
        },
        steps: [step({ key: 'a', status: 'skipped' })],
      }),
    )
    mount(<WorkflowRunPage />)
    const panel = await screen.findByRole('region', {
      name: 'Blocked on dependencies',
    })
    expect(panel).toHaveTextContent('b: blocked by a (skipped)')
    expect(
      within(panel).queryByRole('button', { name: 'Retry step' }),
    ).toBeNull()
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

  it('cancels the run after a second click, with a reason', async () => {
    vi.mocked(fetchWorkflowRun).mockResolvedValue(
      run({ state: 'running', steps: [step({ status: 'running' })] }),
    )
    vi.mocked(cancelWorkflowRun).mockResolvedValue({
      run_id: 'r1',
      state: 'running',
      cancel: CANCEL,
      cancelling: true,
    })
    mount(<WorkflowRunPage />)
    const box = await screen.findByTestId('cancel-run')
    fireEvent.click(within(box).getByRole('button', { name: 'Cancel run' }))
    expect(cancelWorkflowRun).not.toHaveBeenCalled()
    fireEvent.change(within(box).getByLabelText('Reason (optional)'), {
      target: { value: 'wrong branch' },
    })
    fireEvent.click(
      within(box).getByRole('button', { name: 'Confirm: cancel run' }),
    )
    await waitFor(() =>
      expect(cancelWorkflowRun).toHaveBeenCalledWith(
        'r1111111-0000-0000-0000-000000000000',
        'wrong branch',
      ),
    )
  })

  it('backs out of a cancel without sending anything', async () => {
    vi.mocked(fetchWorkflowRun).mockResolvedValue(
      run({ state: 'running', steps: [step({ status: 'running' })] }),
    )
    mount(<WorkflowRunPage />)
    const box = await screen.findByTestId('cancel-run')
    fireEvent.click(within(box).getByRole('button', { name: 'Cancel run' }))
    fireEvent.click(within(box).getByRole('button', { name: 'Keep run going' }))
    expect(
      within(box).getByRole('button', { name: 'Cancel run' }),
    ).toBeInTheDocument()
    expect(cancelWorkflowRun).not.toHaveBeenCalled()
  })

  it('cancels one step and reports a refused request', async () => {
    vi.mocked(fetchWorkflowRun).mockResolvedValue(
      run({
        state: 'running',
        steps: [
          step({ key: 'build', status: 'running' }),
          step({
            key: 'test',
            position: 1,
            status: 'pending',
            attempts: 0,
            attempt_history: [],
          }),
        ],
      }),
    )
    vi.mocked(cancelWorkflowStep).mockRejectedValue(
      new Error('Cancel failed (409): step is already completed'),
    )
    mount(<WorkflowRunPage />)
    const card = (await screen.findAllByTestId('step'))[0]
    const box = within(card).getByTestId('cancel-step')
    fireEvent.click(within(box).getByRole('button', { name: 'Cancel step' }))
    fireEvent.click(
      within(box).getByRole('button', { name: 'Confirm: cancel step' }),
    )
    await waitFor(() =>
      expect(cancelWorkflowStep).toHaveBeenCalledWith(
        'r1111111-0000-0000-0000-000000000000',
        'build',
        undefined,
      ),
    )
    expect(await within(box).findByRole('alert')).toHaveTextContent(
      'step is already completed',
    )
    // The waiting step has its own button.
    expect(screen.getAllByTestId('cancel-step')).toHaveLength(2)
  })

  it('shows a cancel in progress without offering another', async () => {
    vi.mocked(fetchWorkflowRun).mockResolvedValue(
      run({
        state: 'running',
        cancel: CANCEL,
        cancelling: true,
        steps: [step({ status: 'running', cancelling: true })],
      }),
    )
    mount(<WorkflowRunPage />)
    expect(await screen.findAllByText('Cancelling')).toHaveLength(2)
    expect(screen.getByText(/Cancel requested for this run/)).toHaveTextContent(
      'wrong branch',
    )
    expect(screen.queryByRole('button', { name: /^Cancel / })).toBeNull()
  })

  it('shows a cancelled run with who stopped it and stops polling', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.mocked(fetchWorkflowRun).mockResolvedValue(
      run({
        state: 'cancelled',
        cancel: CANCEL,
        steps: [
          step({
            status: 'cancelled',
            cancel: CANCEL,
            attempt_history: [
              attempt({
                status: 'failed',
                outcome: { kind: 'cancelled', requested_model: OPUS_55 },
                served_models: [OPUS_55],
              }),
            ],
          }),
          step({
            key: 'test',
            position: 1,
            status: 'skipped',
            attempts: 0,
            attempt_history: [],
          }),
        ],
      }),
    )
    mount(<WorkflowRunPage />)
    expect(
      await screen.findByText(/This run was cancelled by owner/),
    ).toHaveTextContent('wrong branch')
    // run, step and attempt each say it
    expect(screen.getAllByText('Cancelled').length).toBeGreaterThanOrEqual(3)
    expect(screen.getByText(/Stopped on request/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Cancel / })).toBeNull()
    await act(() => vi.advanceTimersByTimeAsync(30_000))
    expect(fetchWorkflowRun).toHaveBeenCalledTimes(1)
  })

  it('shows the answering model from served_models when served_model is absent', async () => {
    vi.mocked(fetchWorkflowRun).mockResolvedValue(
      run({
        steps: [
          step({
            attempt_history: [
              attempt({
                served_model: null,
                served_models: [CODEX],
                requested_model: CODEX,
                effective_model: CODEX,
              }),
            ],
          }),
        ],
      }),
    )
    mount(<WorkflowRunPage />)
    const card = await screen.findByTestId('attempt')
    expect(card).toHaveTextContent(CODEX)
    expect(card).not.toHaveTextContent('unknown model')
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
