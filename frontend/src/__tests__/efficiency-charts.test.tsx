import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { EfficiencyOverview } from '@/app/admin/components/EfficiencyOverview'
import {
  parseSessionListState,
  sessionScopeParams,
} from '@/app/sessions/hooks/useSessionListState'
import { type ActivityCost, parseActivityCost } from '@/lib/api/activity-cost'
import { type DurationSplit, isDurationSplit } from '@/lib/api/duration-split'
import {
  parseSessionListResponse,
  sessionListSearchParams,
} from '@/lib/api/sessions'
import { activityFixture } from './activity-cost-fixture'

const split: DurationSplit = {
  admin_seconds: 25,
  other_seconds: 75,
  denominator_seconds: 100,
  admin_share: 0.25,
  other_share: 0.75,
  unknown_seconds: 10,
  unknown_share: 0.1,
  tools_sampled: 5,
  tools_missing_duration: 1,
  duration_coverage: 0.8,
  events_truncated: true,
}

function data(): ActivityCost {
  const group = {
    label: 'Implementation',
    sessions: 3,
    duration_split: split,
    usage: {
      ...activityFixture.usage,
      cache_detail_input_tokens: 0,
      cache_read_tokens: 0,
      cache_write_tokens: 0,
    },
    coverage: { usage_sessions: 2, missing_usage_sessions: 1 },
    cost: {
      recorded_calls: 4,
      api_equiv_known_calls: 2,
      cash_known_calls: 0,
      api_equiv_usd: 0,
      cash_usd: null,
    },
  }
  return {
    ...activityFixture,
    duration_split: split,
    by_project: [{ ...group, project_id: 'project/one', label: 'project/one' }],
    by_work_role: [{ ...group, work_role_id: 'implementation' }],
    by_harness: [{ ...group, harness_id: 'codex_cli', label: 'Codex CLI' }],
    work_roles: [
      { id: 'implementation', label: 'Implementation' },
      { id: 'unknown', label: 'Unknown' },
    ],
    harnesses: [{ id: 'codex_cli', label: 'Codex CLI' }],
  }
}

describe('efficiency charts and accounting contracts', () => {
  it('uses weighted server aggregates, discloses unknown time and preserves scope on every group link', () => {
    const activity = data()
    const scope = new URLSearchParams({
      accounting_start: activity.window_start,
      accounting_end: activity.window_end,
      kind: 'coding',
      subagents: '0',
      benchmarks: '0',
      model: 'recorded-model',
    })
    render(<EfficiencyOverview activity={activity} scope={scope} />)
    expect(screen.getByText('25.0%')).toBeInTheDocument()
    expect(screen.getByText('75.0%')).toBeInTheDocument()
    expect(
      screen.getByText(/Unknown 10.0% · duration on 4\/5 calls/),
    ).toHaveTextContent('Capped sample')
    expect(screen.getByText(/weighted by time/)).toBeInTheDocument()
    for (const [button, name, field, value] of [
      ['Projects', 'project/one', 'project', 'project/one'],
      ['Work roles', 'Implementation', 'work_role', 'implementation'],
      ['Harnesses', 'Codex CLI', 'harness', 'codex_cli'],
    ]) {
      fireEvent.click(screen.getByRole('button', { name: button }))
      const href = screen.getByRole('link', { name }).getAttribute('href') ?? ''
      const params = new URL(href, 'https://example.test').searchParams
      expect(params.get(field)).toBe(value)
      expect(params.get('sort')).toBe('admin_share')
      for (const [key, expected] of scope)
        expect(params.get(key)).toBe(expected)
    }
    fireEvent.click(screen.getByText('Coverage and recorded usage'))
    expect(screen.getByText(/API-equivalent value/)).toHaveTextContent(
      '$0.00 (2/4 calls priced). Cash cost: Unavailable (0/4 calls)',
    )
    expect(
      screen.getByText(/Token purpose remains unknown/),
    ).toBeInTheDocument()
  })

  it('preserves known zero admin shares while leaving missing non-wait time unavailable', () => {
    const activity = data()
    const zeroAdmin = {
      ...split,
      admin_seconds: 0,
      admin_share: 0,
      other_seconds: 100,
      other_share: 1,
    }
    const { rerender } = render(
      <EfficiencyOverview
        activity={{ ...activity, duration_split: zeroAdmin }}
        scope={new URLSearchParams()}
      />,
    )
    expect(screen.getByText('0.0%')).toBeInTheDocument()
    expect(screen.getByText('100.0%')).toBeInTheDocument()
    const empty = {
      ...split,
      admin_seconds: 0,
      other_seconds: 0,
      unknown_seconds: 0,
      denominator_seconds: 0,
      admin_share: null,
      other_share: null,
      unknown_share: null,
    }
    rerender(
      <EfficiencyOverview
        activity={{ ...activity, duration_split: empty, by_project: [] }}
        scope={new URLSearchParams()}
      />,
    )
    expect(screen.getAllByText('Unavailable')).toHaveLength(2)
    expect(
      screen.getByText(/No recorded non-wait tool time/),
    ).toBeInTheDocument()
    expect(
      isDurationSplit({
        ...empty,
        tools_sampled: 1,
        tools_missing_duration: 0,
        duration_coverage: 1,
      }),
    ).toBe(true)
    expect(isDurationSplit({ ...empty, admin_share: 0 })).toBe(false)
  })

  it('validates grouped measures, cost coverage and additive Sessions fields at the boundary', () => {
    const activity = data()
    expect(parseActivityCost(activity)).toEqual(activity)
    for (const bad of [
      { duration_split: { ...split, admin_share: NaN } },
      {
        by_harness: [
          {
            ...activity.by_harness?.[0],
            cost: {
              recorded_calls: 1,
              api_equiv_known_calls: 2,
              cash_known_calls: 0,
              api_equiv_usd: 0,
              cash_usd: null,
            },
          },
        ],
      },
      {
        by_work_role: [
          { ...activity.by_work_role?.[0], usage: { input_tokens: '1' } },
        ],
      },
    ])
      expect(() => parseActivityCost({ ...activity, ...bad })).toThrow()
    const response = {
      sessions: [{ id: 's', work_role: null, activity_accounting: split }],
      total: 1,
      accounting_window: {
        start: activity.window_start,
        end: activity.window_end,
      },
    }
    expect(parseSessionListResponse(response)).toEqual(response)
    expect(() =>
      parseSessionListResponse({
        ...response,
        sessions: [
          {
            id: 's',
            activity_accounting: { ...split, tools_missing_duration: 99 },
          },
        ],
      }),
    ).toThrow()
    expect(
      parseSessionListResponse({ sessions: [{ id: 'legacy' }], total: 1 })
        .sessions[0].activity_accounting,
    ).toBeUndefined()
  })

  it('serializes exact accounting dates, role/harness and server sort without averaging rows', () => {
    const params = sessionListSearchParams({
      accounting_start: activityFixture.window_start,
      accounting_end: activityFixture.window_end,
      work_role: 'unknown',
      harness: 'pi',
      sort_by: 'admin_duration',
      sort_direction: 'desc',
      cursor: 'next-page',
    })
    expect(Object.fromEntries(params)).toMatchObject({
      work_role: 'unknown',
      harness: 'pi',
      accounting_start: activityFixture.window_start,
      accounting_end: activityFixture.window_end,
      sort_by: 'admin_duration',
      cursor: 'next-page',
    })
    const state = parseSessionListState(
      new URLSearchParams(
        'kind=coding&subagents=0&benchmarks=0&work_role=unknown&harness=pi&sort=admin_share&accounting_start=2026-10-21T12:00:00Z&accounting_end=2026-10-22T12:00:00Z',
      ),
    )
    expect(parseSessionListState(sessionScopeParams(state))).toEqual(state)
  })
})
