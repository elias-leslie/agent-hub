import { describe, expect, it } from 'vitest'
import {
  buildSessionDetailBlocks,
  pairToolEvents,
} from '@/app/persona/components/workspace-event-details'
import { buildTranscriptItems } from '@/app/persona/components/workspace-transcript'
import type { TimelineEvent } from '@/types/events'

function event(
  id: string,
  eventType: TimelineEvent['event_type'],
  overrides: Partial<TimelineEvent> = {},
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
    created_at: '2026-09-23T12:00:00Z',
    ...overrides,
  }
}

describe('persona tool pairing', () => {
  it('pairs native results by call ID across intervening events and absent result names', () => {
    const events = [
      event('call', 'tool_use', {
        call_id: 'call-123',
        tool_name: 'functions.exec',
        tool_input: { command: 'pwd' },
      }),
      event('message', 'assistant_message', { content: 'Waiting for tool' }),
      event('result', 'tool_result', {
        call_id: 'call-123',
        tool_output: { output: '/workspace' },
      }),
    ]

    expect([...pairToolEvents(events)]).toEqual([[0, 2]])
    const detailBlocks = buildSessionDetailBlocks(events)
    expect(detailBlocks).toHaveLength(2)
    expect(detailBlocks[0]).toMatchObject({
      id: 'call:result',
      title: 'functions.exec',
      lead: '/workspace',
    })
    const transcript = buildTranscriptItems(events)
    expect(transcript.filter((item) => item.kind === 'tool_call')).toEqual([
      expect.objectContaining({
        id: 'call',
        toolName: 'functions.exec',
        toolResult: '/workspace',
      }),
    ])
  })

  it('keeps legacy adjacent matching but never pairs different native identities', () => {
    const legacy = [
      event('legacy-call', 'tool_use', { tool_name: 'Read' }),
      event('legacy-result', 'tool_result', {
        tool_name: 'Read',
        tool_output: { output: 'ok' },
      }),
    ]
    expect([...pairToolEvents(legacy)]).toEqual([[0, 1]])

    const mismatched = [
      event('call', 'tool_use', { call_id: 'a', tool_name: 'Read' }),
      event('result', 'tool_result', {
        call_id: 'b',
        tool_name: 'Read',
      }),
    ]
    expect(pairToolEvents(mismatched).size).toBe(0)
    expect(buildSessionDetailBlocks(mismatched)).toHaveLength(2)
  })
})
