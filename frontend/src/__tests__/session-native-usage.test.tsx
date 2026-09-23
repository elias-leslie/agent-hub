import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import {
  NativeUsage,
  summarizeNativeUsage,
} from '@/app/sessions/[id]/components/NativeUsage'
import type { TimelineEvent } from '@/types/events'

function event(
  id: string,
  eventType: TimelineEvent['event_type'],
  usage: Record<string, unknown> | null,
): TimelineEvent {
  return {
    id,
    turn: 1,
    sequence: 1,
    event_type: eventType,
    role: null,
    content: null,
    tool_name: null,
    tool_input: null,
    tool_output: null,
    tokens: null,
    duration_ms: null,
    model_used: null,
    agent_id: null,
    agent_name: null,
    usage,
    created_at: '2026-09-23T12:00:00Z',
  }
}

describe('native session usage', () => {
  it('shows missing data as unavailable rather than zero', () => {
    render(<NativeUsage events={[]} totalEvents={0} />)

    expect(
      screen.getByText(/no per-response native usage in loaded events/i),
    ).toBeInTheDocument()
    expect(screen.getAllByText('Unavailable')).toHaveLength(5)
    expect(screen.queryByText('0')).not.toBeInTheDocument()
  })

  it('deduplicates response identities, preserves explicit zero, and exposes field coverage', () => {
    const response = event('evt-1', 'usage', {
      scope: 'response',
      source: 'codex.token_usage_record.usage',
      response_id: 'response-1',
      input_tokens: 0,
      output_tokens: 7,
      cached_input_tokens: 0,
    })
    const second = event('evt-2', 'usage', {
      scope: 'response',
      source: 'codex.token_usage_record.usage',
      response_id: 'response-2',
      input_tokens: 4,
      output_tokens: 6,
    })
    const summary = summarizeNativeUsage([
      response,
      { ...response, id: 'replayed' },
      second,
    ])

    expect(summary.responseCount).toBe(2)
    expect(summary.counts.input_tokens).toEqual({ value: 4, recorded: 2 })
    expect(summary.counts.output_tokens).toEqual({ value: 13, recorded: 2 })
    expect(summary.counts.cached_input_tokens).toEqual({
      value: 0,
      recorded: 1,
    })

    render(<NativeUsage events={[response, second]} totalEvents={5} />)
    const cached = screen.getByText('Cached input').closest('div')
    expect(cached).not.toBeNull()
    expect(within(cached as HTMLElement).getByText('0')).toBeInTheDocument()
    expect(
      within(cached as HTMLElement).getByText('1/2 response records'),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/coverage of all model responses is unknown/i),
    ).toBeInTheDocument()
    expect(
      screen.getByText('Inspected 2 of 5 session events.'),
    ).toBeInTheDocument()
  })

  it('keeps cumulative turn and thread observations separate from response sums', () => {
    const events = [
      event('response', 'usage', {
        scope: 'response',
        source: 'codex.token_usage_record.usage',
        input_tokens: 10,
        output_tokens: 2,
      }),
      event('thread-old', 'usage_counter', {
        scope: 'thread',
        source: 'codex.event_msg.token_count.total_token_usage',
        input_tokens: 100,
      }),
      event('thread-new', 'usage_counter', {
        scope: 'thread',
        source: 'codex.event_msg.token_count.total_token_usage',
        input_tokens: 120,
      }),
      event('turn', 'usage_counter', {
        scope: 'turn',
        source: 'codex.token_usage_record.turn_token_usage',
        input_tokens: 30,
      }),
    ]
    const summary = summarizeNativeUsage(events)

    expect(summary.counts.input_tokens.value).toBe(10)
    expect(
      summary.latestCounters.find((item) => item.scope === 'thread')?.counts
        .input_tokens.value,
    ).toBe(120)
    expect(
      summary.latestCounters.find((item) => item.scope === 'turn')?.counts
        .input_tokens.value,
    ).toBe(30)
    render(<NativeUsage events={events} totalEvents={events.length} />)
    expect(screen.getByText(/not added to response usage/i)).toBeInTheDocument()
    expect(
      screen.getByText(/child sessions are not included/i),
    ).toBeInTheDocument()
  })
})
