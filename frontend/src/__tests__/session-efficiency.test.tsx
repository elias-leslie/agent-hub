import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { SessionEfficiency } from '@/app/admin/components/SessionEfficiency'
import {
  type ActivityCost,
  activitySessionParams,
  activitySessionsHref,
  parseActivityCost,
} from '@/lib/api/activity-cost'
import { activityFixture } from './activity-cost-fixture'
import snapshot from './fixtures/session-efficiency-snapshot.json'

function data(): ActivityCost {
  const result = parseActivityCost(snapshot)
  if (!result?.session_efficiency)
    throw new Error('Missing synthetic session fixture')
  return result
}

describe('session efficiency review', () => {
  it('renders the backend-generated session ranking, source measures and review routine', () => {
    const activity = data()
    render(<SessionEfficiency activity={activity} />)
    expect(
      screen.getByText(/ranked by estimated admin tool-context tokens/),
    ).toHaveTextContent('Showing 4 of 4 sessions')
    expect(
      screen.getByText(
        /project · admin · Estimated tool context: Admin 68.1% · Other 31.9% · 94 est. tokens/,
      ),
    ).toBeInTheDocument()
    const summary = screen.getByText(/project · admin · Estimated tool context/)
    fireEvent.click(summary)
    expect(summary.closest('details')).toHaveAttribute('open')
    expect(screen.getByText('st.context: 2 calls · 10s')).toBeInTheDocument()
    expect(screen.getByText(/3 \/ 3 calls have duration/)).toHaveTextContent(
      'Sampled event span: 40s',
    )
    expect(
      screen.getAllByText(/causal admin token spend is unknown/),
    ).toHaveLength(4)
    expect(
      screen.getByText(/1,010 recorded provider tokens/),
    ).toBeInTheDocument()
    expect(screen.getAllByText(/Provider usage unavailable/)).toHaveLength(3)
    expect(
      screen.getByRole('link', { name: 'Review session admin' }),
    ).toHaveAttribute(
      'href',
      activitySessionsHref('project', 'admin', activitySessionParams(activity)),
    )
    const routine = screen.getByText('Lean session review routine')
    fireEvent.click(routine)
    expect(routine.closest('details')).toHaveAttribute('open')
    expect(
      screen.getByText(/No per-command reporting or new form/),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/Admin \+ support includes necessary work/),
    ).toBeInTheDocument()
  })

  it('preserves unavailable older-server data and empty sessions', () => {
    const { rerender } = render(
      <SessionEfficiency activity={activityFixture} />,
    )
    expect(
      screen.getByText('Session efficiency is unavailable from this server.'),
    ).toBeInTheDocument()
    const activity = data()
    const efficiency = activity.session_efficiency
    if (!efficiency) throw new Error('Missing fixture')
    rerender(
      <SessionEfficiency
        activity={{
          ...activity,
          session_efficiency: { ...efficiency, rows: [], sessions_total: 0 },
        }}
      />,
    )
    expect(screen.getByText('No sessions in this window.')).toBeInTheDocument()
  })

  it('shows session token partitions with partial, unavailable and known-zero cache detail', () => {
    const activity = data()
    const efficiency = activity.session_efficiency
    const row = efficiency?.rows.find((item) => item.session_id === 'tokens')
    if (!efficiency || !row) throw new Error('Missing usage fixture')
    const withUsage = (usage: typeof row.usage): ActivityCost => ({
      ...activity,
      session_efficiency: {
        ...efficiency,
        rows: efficiency.rows.map((item) =>
          item.session_id === row.session_id
            ? {
                ...item,
                usage,
                tokens: usage.input_tokens + usage.output_tokens,
              }
            : item,
        ),
      },
    })
    const { rerender } = render(<SessionEfficiency activity={activity} />)
    expect(
      screen.getAllByText('Provider token partitions unavailable.'),
    ).toHaveLength(3)
    expect(
      screen.getByText(/Input 1,000 · output 10 tokens/),
    ).toHaveTextContent(
      'Cache read/write unavailable. Cache detail covers 0 / 1,000 input tokens. Uncovered input has an unknown cache split.',
    )
    rerender(
      <SessionEfficiency
        activity={withUsage({
          ...row.usage,
          cache_read_tokens: 600,
          cache_write_tokens: 100,
          cache_detail_input_tokens: 800,
        })}
      />,
    )
    expect(
      screen.getByText(/Input 1,000 · output 10 tokens/),
    ).toHaveTextContent(
      'Recorded cache read 600 · cache write 100 tokens. Cache detail covers 800 / 1,000 input tokens. Uncovered input has an unknown cache split.',
    )
    rerender(
      <SessionEfficiency
        activity={withUsage({ ...row.usage, cache_detail_input_tokens: 1000 })}
      />,
    )
    expect(
      screen.getByText(/Input 1,000 · output 10 tokens/),
    ).toHaveTextContent(
      'Recorded cache read 0 · cache write 0 tokens. Cache detail covers 1,000 / 1,000 input tokens.',
    )
    expect(
      screen.queryByText(/Uncovered input has an unknown cache split/),
    ).not.toBeInTheDocument()
    rerender(
      <SessionEfficiency
        activity={withUsage({
          input_tokens: 0,
          output_tokens: 0,
          cache_read_tokens: 0,
          cache_write_tokens: 0,
          cache_detail_input_tokens: 0,
        })}
      />,
    )
    expect(screen.getByText(/Input 0 · output 0 tokens/)).toHaveTextContent(
      'Recorded cache read 0 · cache write 0 tokens. Cache detail covers 0 / 0 input tokens.',
    )
  })

  it('keeps configured goals, unselected goals and limited coverage distinct', () => {
    const activity = data()
    const efficiency = activity.session_efficiency
    if (!efficiency) throw new Error('Missing fixture')
    const { rerender } = render(
      <SessionEfficiency
        activity={{
          ...activity,
          session_efficiency: {
            ...efficiency,
            goal: { ...efficiency.goal, admin_share_target: null },
          },
        }}
      />,
    )
    expect(screen.getByText(/Admin-share target is unset/)).toBeInTheDocument()
    rerender(
      <SessionEfficiency
        activity={{
          ...activity,
          session_efficiency: {
            ...efficiency,
            goal: { ...efficiency.goal, admin_share_target: 0.4 },
            rows: efficiency.rows.map((row) => ({
              ...row,
              goal_status: 'insufficient_coverage',
            })),
          },
        }}
      />,
    )
    expect(screen.getByText(/admin \+ support ≤ 40.0%/)).toBeInTheDocument()
    expect(
      screen.getAllByText(/Limited coverage for admin share/),
    ).toHaveLength(4)
  })

  it('rejects malformed session measures at the external boundary', () => {
    for (const changed of [
      { trial_goal: { relative_cost_reduction_target: -1 } },
      { goal: { ...snapshot.session_efficiency.goal, admin_share_target: 2 } },
      {
        status_counts: {
          ...snapshot.session_efficiency.status_counts,
          within_goal: 99,
        },
      },
      { rows: [{ ...snapshot.session_efficiency.rows[0], tool_time: null }] },
      {
        rows: [
          {
            ...snapshot.session_efficiency.rows[0],
            tools_missing_duration: 99,
          },
        ],
      },
      {
        rows: [
          { ...snapshot.session_efficiency.rows[0], goal_status: 'productive' },
        ],
      },
      {
        rows: [
          {
            ...snapshot.session_efficiency.rows[0],
            repeat_admin_patterns: [
              { family: 'x', calls: -1, measured_tool_seconds: 0 },
            ],
          },
        ],
      },
    ]) {
      expect(() =>
        parseActivityCost({
          ...snapshot,
          session_efficiency: { ...snapshot.session_efficiency, ...changed },
        }),
      ).toThrow()
    }
  })
})
