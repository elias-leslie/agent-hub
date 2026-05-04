import { describe, expect, it } from 'vitest'
import { summarizeSessionMemoryObservability } from '@/lib/session-memory-observability'
import type { TimelineEvent } from '@/types/events'

function makeEvent(overrides: Partial<TimelineEvent>): TimelineEvent {
  return {
    id: 'evt-1',
    turn: 1,
    sequence: 1,
    event_type: 'thinking',
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
    created_at: '2026-03-07T18:00:00Z',
    ...overrides,
  }
}

describe('session memory observability', () => {
  it('summarizes selected, indexed, and cited references from session events', () => {
    const summary = summarizeSessionMemoryObservability([
      makeEvent({
        event_type: 'memory_inject',
        tool_input: {
          reference_selected_count: 3,
          reference_index_count: 29,
          reference_selected_uuids: ['ref-1', 'ref-2', 'ref-3'],
        },
      }),
      makeEvent({
        id: 'evt-2',
        sequence: 2,
        event_type: 'memory_cite',
        tool_input: {
          uuids: ['ref-1', 'mandate-1', 'ref-2'],
        },
      }),
    ])

    expect(summary).toEqual({
      selectedCount: 3,
      indexCount: 29,
      selectedCitedCount: 2,
      totalCitedCount: 3,
      selectedCitationRate: 67,
    })
  })

  it('returns null when the session has no memory observability data', () => {
    const summary = summarizeSessionMemoryObservability([
      makeEvent({ event_type: 'assistant_message', content: 'hello' }),
    ])

    expect(summary).toBeNull()
  })
})
