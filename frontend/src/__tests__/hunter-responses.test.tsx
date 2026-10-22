import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { HunterResponseActivity } from '@/app/admin/components/HunterResponseActivity'
import { parseActivityCost } from '@/lib/api/activity-cost'
import { activityFixture } from './activity-cost-fixture'
import sample from './fixtures/hunter-responses.json'

const activity = { ...activityFixture, hunter_responses: sample }

function parsed(value: unknown = activity) {
  const data = parseActivityCost(value)
  if (!data) throw new Error('Missing synthetic activity sample')
  return data
}

describe('Neri response accounting', () => {
  it('accepts the backend sample and keeps response shares, token shares and per-response input distinct', () => {
    const data = parsed()
    render(<HunterResponseActivity activity={data} />)
    const disclosure = screen.getByText(/Neri hunter responses/)
    fireEvent.click(disclosure)
    expect(disclosure.parentElement).toHaveAttribute('open')
    expect(screen.getByRole('table')).toHaveTextContent('Investigation only')
    expect(screen.getByRole('table')).toHaveTextContent('Mixed')
    expect(screen.getByRole('table')).toHaveTextContent('Unknown')
    expect(screen.getAllByText('1 · 25.0%')).toHaveLength(4)
    expect(screen.getByText('220 · 20.4%')).toBeInTheDocument()
    expect(
      screen.getByText(/first 100 → peak 400 tokens at sampled response 4/),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/First observed investigation: Source read/),
    ).toHaveTextContent(
      'sampled response 2 · 10s since first sampled response · input 200 tokens',
    )
    expect(
      screen.getByText(/Cumulative reported input 1,000/),
    ).toHaveTextContent('output 80')
    expect(screen.getByRole('link', { name: 's' })).toHaveAttribute(
      'href',
      expect.stringContaining('project=neri&sel=s'),
    )
  })

  it('distinguishes unavailable, empty and capped data', () => {
    const view = render(<HunterResponseActivity activity={activityFixture} />)
    expect(screen.getByText(/unavailable from this server/)).toBeInTheDocument()
    view.rerender(
      <HunterResponseActivity
        activity={parsed({
          ...activity,
          hunter_responses: { ...sample, sessions_total: 0, rows: [] },
        })}
      />,
    )
    expect(
      screen.getByText(/No declared Neri hunting or recon sessions/),
    ).toBeInTheDocument()
    view.rerender(
      <HunterResponseActivity
        activity={parsed({
          ...activity,
          hunter_responses: { ...sample, events_truncated: true },
        })}
      />,
    )
    expect(screen.getByText(/Event sample capped/)).toHaveTextContent(
      'categories are unknown',
    )
  })

  it('keeps missing response numbers and zero input meaningful', () => {
    const first = sample.rows[0]
    render(
      <HunterResponseActivity
        activity={parsed({
          ...activity,
          hunter_responses: {
            ...sample,
            rows: [
              {
                ...first,
                first_observed_investigation: {
                  action: 'source_read',
                  sample_response_number: null,
                  seconds_from_first_response: 0,
                  input_tokens: null,
                },
                input_per_response: {
                  first_tokens: 0,
                  peak_tokens: 0,
                  peak_sample_response_number: 1,
                },
                window_starts_mid_session: true,
              },
            ],
          },
        })}
      />,
    )
    expect(screen.getByText(/sampled response Unavailable/)).toHaveTextContent(
      '0s since first sampled response · input Unavailable',
    )
    expect(screen.getByText(/first 0 → peak 0/)).toBeInTheDocument()
    expect(
      screen.getByText(/This window starts after the session began/),
    ).toBeInTheDocument()
  })

  it('rejects malformed or inconsistent response metrics at the existing API boundary', () => {
    for (const bad of [
      { ...sample, responses: 99 },
      { ...sample, tokens: 5 },
      { ...sample, breakdown: sample.breakdown.slice(1) },
      { ...sample, rows: [{ ...sample.rows[0], input_per_response: {} }] },
      { ...sample, usage: { ...sample.usage, cache_read_tokens: -1 } },
    ]) {
      expect(() => parsed({ ...activity, hunter_responses: bad })).toThrow(
        /invalid/,
      )
    }
  })
})
