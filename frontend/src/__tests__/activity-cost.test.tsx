import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ActivityCostPanel } from '@/app/admin/components/ActivityCostPanel'
import { parseSessionListState } from '@/app/sessions/hooks/useSessionListState'
import {
  activitySessionsHref,
  parseActivityCost,
} from '@/lib/api/activity-cost'
import { activityFixture as activity } from './activity-cost-fixture'

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
