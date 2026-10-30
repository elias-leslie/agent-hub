import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { parseSessionListState } from '@/app/sessions/hooks/useSessionListState'
import { ActivityCostPanel } from '@/app/token-share/components/ActivityCostPanel'
import { SessionHotspotsPanel } from '@/app/token-share/components/SessionHotspotsPanel'
import {
  activitySessionParams,
  activitySessionsHref,
  parseActivityCost,
} from '@/lib/api/activity-cost'
import { activityFixture as activity } from './activity-cost-fixture'
import backendSnapshot from './fixtures/activity-accounting-snapshot.json'
import stSnapshot from './fixtures/st-activity-snapshot.json'

function panel(data = activity, error: string | null = null) {
  return (
    <ActivityCostPanel
      activity={data}
      error={error}
      isLoading={false}
      onRetry={vi.fn()}
    />
  )
}

describe('activity observations', () => {
  it('shows measured shares, denominators, coverage and visible caps without claiming waste', () => {
    render(panel())
    expect(screen.getByText('50.0%')).toBeInTheDocument()
    expect(screen.getByText('50s / 100s')).toBeInTheDocument()
    expect(screen.getByText(/CAPPED: recent events only/)).toBeInTheDocument()
    expect(screen.getByText(/3 \/ 10 observed tool calls/)).toBeInTheDocument()
    expect(
      screen.getByText(/3 \/ 4 sessions have no single reliable task link/),
    ).toBeInTheDocument()
    expect(screen.getByText(/Showing 1 of 8 families/)).toBeInTheDocument()
    expect(screen.getByText(/Showing 1 of 7 tasks/)).toBeInTheDocument()
    expect(screen.getByText('Projects shown: 1 / 2')).toBeInTheDocument()
    expect(
      screen.getByText(/includes necessary checks, commits and builds/),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/not token, spend or total-work shares/),
    ).toBeInTheDocument()
  })

  it('keeps recorded usage and the admin history estimate distinct', () => {
    render(panel())
    expect(
      screen.getByRole('heading', { name: 'Recorded tokens' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('heading', { name: 'Admin transcript estimate' }),
    ).toBeInTheDocument()
    expect(screen.getByText('200 characters · 50.0%')).toBeInTheDocument()
    expect(
      screen.getByText(/100 argument characters \+ 300 returned characters/),
    ).toHaveTextContent('7 / 10 sampled calls')
    expect(
      screen.getByText(/context still resident after compaction/),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/800 cache read and 20 cache write/),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('link', { name: 'project/one · s&1' }),
    ).toHaveAttribute(
      'href',
      activitySessionsHref(
        'project/one',
        's&1',
        activitySessionParams(activity),
      ),
    )
    expect(
      screen.getByRole('heading', { name: 'Projects by recorded tokens' }),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/accounting calls have no matching Hub session/),
    ).toBeInTheDocument()
  })

  it('rejects missing accounting evidence and malformed nested ranking data', () => {
    expect(() =>
      parseActivityCost({ ...activity, transcript: undefined }),
    ).toThrow()
    expect(() =>
      parseActivityCost({
        ...activity,
        usage: { ...activity.usage, cache_read_tokens: 9000 },
      }),
    ).toThrow()
    expect(() =>
      parseActivityCost({
        ...activity,
        project_rankings: [
          {
            ...activity.project_rankings[0],
            transcript: { ...activity.transcript, breakdown: [] },
          },
        ],
      }),
    ).toThrow()
    expect(() =>
      parseActivityCost({
        ...activity,
        tokens: { ...activity.tokens, unclassified_share: NaN },
      }),
    ).toThrow()
  })

  it('accepts and displays the backend-generated accounting fixture', () => {
    const data = parseActivityCost(backendSnapshot)
    render(
      <ActivityCostPanel
        activity={data}
        error={null}
        isLoading={false}
        onRetry={vi.fn()}
      />,
    )
    expect(screen.getByText('3,230')).toBeInTheDocument()
    expect(screen.getByText('533 characters · 95.5%')).toBeInTheDocument()
    expect(
      screen.getByText(/110 tokens from 1 accounting calls/),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/0 \/ 2 observed tool calls lack usable duration/),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('link', { name: 'Open a linked session for task-real' }),
    ).toHaveAttribute(
      'href',
      activitySessionsHref('p1', 's', activitySessionParams(backendSnapshot)),
    )
  })

  it('displays the backend ST sample with measured and estimated coverage separate', () => {
    const data = parseActivityCost(stSnapshot)
    if (!data) throw new Error('Missing synthetic Activity snapshot')
    render(panel(data))
    expect(
      screen.getByText(
        /4 ST commands in sampled calls · 2s elapsed · ~19 input text tokens · ~21 output text tokens/,
      ),
    ).toBeInTheDocument()
    const disclosure = screen.getByText('Top ST families and coverage')
    fireEvent.click(disclosure)
    expect(disclosure.closest('details')).toHaveAttribute('open')
    expect(screen.getByText(/Showing 4 of 4 families/)).toBeInTheDocument()
    expect(
      screen.getByText(/2 commands share shell results/),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/1 shell calls could not be parsed/),
    ).toBeInTheDocument()
    expect(screen.getByText('st.web · Substantive')).toBeInTheDocument()
    expect(screen.getByText('st.context · Admin')).toBeInTheDocument()
    expect(screen.getByText('st.check · Support')).toBeInTheDocument()
    expect(
      screen.getByText(
        /Input tokenized for 4\/4 commands; the rest use a character estimate/,
      ),
    ).toBeInTheDocument()
    expect(screen.getAllByText(/Time unavailable/)).toHaveLength(2)
    expect(
      screen.getByRole('link', { name: 'Open an observed st.context session' }),
    ).toHaveAttribute(
      'href',
      activitySessionsHref('project', 's', activitySessionParams(stSnapshot)),
    )
    expect(screen.queryByText('task-synthetic')).not.toBeInTheDocument()
    expect(
      screen.getByText(/separate from provider usage, billed tokens/),
    ).toBeInTheDocument()
  })

  it('keeps older-server ST data unavailable and rejects invalid ST metrics', () => {
    render(panel())
    expect(
      screen.getByText('ST command data is unavailable from this server.'),
    ).toBeInTheDocument()
    expect(() =>
      parseActivityCost({
        ...stSnapshot,
        st_commands: { ...stSnapshot.st_commands, measured_seconds: -1 },
      }),
    ).toThrow()
    expect(() =>
      parseActivityCost({
        ...stSnapshot,
        st_commands: { ...stSnapshot.st_commands, commands_with_output: 99 },
      }),
    ).toThrow()
    expect(() =>
      parseActivityCost({
        ...stSnapshot,
        st_commands: {
          ...stSnapshot.st_commands,
          families: [
            { ...stSnapshot.st_commands.families[0], category: 'invented' },
          ],
        },
      }),
    ).toThrow()
  })

  it('shows input fallback coverage without dropping measured time or output', () => {
    const value = {
      ...stSnapshot,
      st_commands: {
        ...stSnapshot.st_commands,
        commands_with_tokenized_input: 1,
        families: stSnapshot.st_commands.families.map((row, index) => ({
          ...row,
          commands_with_tokenized_input: index === 0 ? 1 : 0,
        })),
      },
    }
    const data = parseActivityCost(value)
    if (!data) throw new Error('Missing synthetic Activity snapshot')
    render(panel(data))
    expect(
      screen.getByText(
        /Input tokenized for 1\/4 commands; the rest use a character estimate/,
      ),
    ).toBeInTheDocument()
    expect(
      screen.getByText(
        /4 ST commands in sampled calls · 2s elapsed · ~19 input text tokens · ~21 output text tokens/,
      ),
    ).toBeInTheDocument()
    expect(() =>
      parseActivityCost({
        ...value,
        st_commands: { ...value.st_commands, commands_with_tokenized_input: 5 },
      }),
    ).toThrow()
  })

  it('omits the incompatible legacy Window Cost card while retaining diagnostics', () => {
    render(
      <SessionHotspotsPanel
        isLoading={false}
        hotspots={{
          generated_at: activity.window_end,
          window_hours: 24,
          totals: {
            sessions: 4,
            input_tokens: 126,
            output_tokens: 29000,
            total_cost_usd: 42,
            active_sessions: 1,
            zero_event_active_sessions: 0,
            rate_limit_fallback_sessions: 0,
            missing_attribution_sessions: 0,
          },
          attribution_breakdown: [],
          repeated_workloads: [],
          low_yield_sessions: [],
          zero_event_active_sessions: [],
        }}
      />,
    )
    expect(screen.queryByText('Window Cost')).not.toBeInTheDocument()
    expect(screen.queryByText('$42.00')).not.toBeInTheDocument()
    expect(screen.getByText('Rate-Limit Fallbacks')).toBeInTheDocument()
  })

  it('labels missing session usage separately from recorded zero', () => {
    render(
      panel({
        ...activity,
        session_rankings: [
          {
            ...activity.session_rankings[0],
            usage_source: 'missing',
            tokens: 0,
          },
        ],
      }),
    )
    expect(screen.getByText(/codex · Usage unavailable/)).toBeInTheDocument()
  })

  it('opens source-backed sessions with all kinds, children and benchmarks included', () => {
    render(panel())
    const href = screen
      .getByRole('link', { name: 'Open st.context session in project/one' })
      .getAttribute('href')
    const state = parseSessionListState(
      new URL(href ?? '', 'https://example.test').searchParams,
    )
    expect(state).toMatchObject({
      project: 'project/one',
      selected: 's&1',
      since: 'all',
      includeSubagents: true,
      includeBenchmarks: true,
    })
    expect(state.kinds).toHaveLength(4)
    expect(
      screen.getByRole('link', { name: 'Open a linked session for task-real' }),
    ).toHaveAttribute('href', href)
    expect(activitySessionsHref('a&b')).toContain('project=a%26b')
  })

  it('distinguishes loading, unavailable, empty and failed requests, and retries', () => {
    const retry = vi.fn()
    const { rerender } = render(
      <ActivityCostPanel
        activity={null}
        error={null}
        isLoading
        onRetry={retry}
      />,
    )
    expect(screen.getByRole('status')).toHaveTextContent('Loading activity')
    rerender(
      <ActivityCostPanel
        activity={null}
        error={null}
        isLoading={false}
        onRetry={retry}
      />,
    )
    expect(screen.getByText(/unavailable from this server/)).toBeInTheDocument()
    rerender(
      <ActivityCostPanel
        activity={null}
        error="Forbidden (403)"
        isLoading={false}
        onRetry={retry}
      />,
    )
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Activity could not be loaded',
    )
    fireEvent.click(screen.getByRole('button', { name: 'Retry activity' }))
    expect(retry).toHaveBeenCalledOnce()
    rerender(
      panel({
        ...activity,
        tool_time: { ...activity.tool_time, denominator_seconds: 0 },
        repeat_admin_patterns: [],
        repeat_admin_patterns_total: 0,
        task_rollups: [],
        task_rollups_total: 0,
      }),
    )
    expect(screen.getByText(/Shares are unavailable/)).toBeInTheDocument()
    expect(screen.queryByText('50.0%')).not.toBeInTheDocument()
    expect(screen.getByText(/No repeated admin families/)).toBeInTheDocument()
    expect(screen.getByText(/No unambiguous task links/)).toBeInTheDocument()
    rerender(panel(activity, 'Request failed'))
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Showing the last loaded snapshot',
    )
    expect(screen.getByText('50s / 100s')).toBeInTheDocument()
  })

  it('validates external activity data and preserves unavailable and zero values', () => {
    expect(parseActivityCost(activity)).toEqual(activity)
    expect(parseActivityCost(undefined)).toBeNull()
    expect(() =>
      parseActivityCost({ ...activity, tools_sampled: undefined }),
    ).toThrow('incomplete or invalid')
    expect(() =>
      parseActivityCost({ ...activity, events_sampled: '20' }),
    ).toThrow()
    expect(() =>
      parseActivityCost({
        ...activity,
        tool_time: {
          ...activity.tool_time,
          breakdown: [{ category: 'invented', seconds: 1, share: 1 }],
        },
      }),
    ).toThrow()
    expect(() =>
      parseActivityCost({
        ...activity,
        task_rollups: [
          { ...activity.task_rollups[0], sample_session_id: null },
        ],
      }),
    ).toThrow()
    expect(parseActivityCost({ ...activity, sessions: 0 })?.sessions).toBe(0)
  })
})
