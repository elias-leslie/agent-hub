import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { EventTimeline } from '@/components/timeline'
import {
  combineNativeEvidencePages,
  nativeEvidenceNextCursor,
  parseNativeEvidenceSummary,
} from '@/lib/api/native-evidence'
import type { TimelineEvent } from '@/types/events'

const event: TimelineEvent = {
  id: 'event',
  turn: 1,
  sequence: 1,
  event_type: 'tool_use',
  role: null,
  content: null,
  tool_name: 'toy command',
  tool_input: { command: 'toy' },
  tool_output: null,
  tokens: 0,
  duration_ms: 0,
  model_used: null,
  agent_id: null,
  agent_name: null,
  created_at: '2026-10-01T12:00:00Z',
}
const summary = {
  schema_version: 'native-observation.v1',
  session_id: 'session',
  next_entity_id: 'entity',
  provenance_truncated: false,
  inherited_receipt_count: 2,
  unresolved_receipt_count: 1,
  approvals: {
    validated_requests: 1,
    bound_responses: 1,
    cleared_requests: 0,
    unresolved: 0,
  },
  usage_authority: 'rollout',
  observed_model: null,
  commands: [
    {
      entity_id: 'entity',
      projection_event_ids: ['event'],
      status: 'reconciled',
      observed_model: null,
      receipts: [
        {
          source_id: 'live-source',
          position: 3,
          source_kind: 'app_server',
          authenticity: 'collector_attested',
          origin: 'live',
          disposition: 'accounted',
        },
        {
          source_id: 'rollout-source',
          position: 1,
          source_kind: 'rollout',
          authenticity: 'local_verified',
          origin: 'rollout_record',
          disposition: 'reconciled',
        },
      ],
    },
  ],
}

describe('canonical event provenance', () => {
  it('keeps each page bounded and does not add session audit counts across pages', () => {
    const first = parseNativeEvidenceSummary(summary)
    const full = {
      ...first,
      commands: Array.from({ length: 100 }, (_, index) => ({
        ...first.commands[0],
        entity_id: `entity-${index}`,
      })),
      next_entity_id: 'entity-99',
    }
    expect(nativeEvidenceNextCursor(full)).toBe('entity-99')
    expect(nativeEvidenceNextCursor(first)).toBeUndefined()
    const combined = combineNativeEvidencePages([
      first,
      { ...full, provenance_truncated: true },
    ])
    expect(combined?.commands).toHaveLength(101)
    expect(combined?.inherited_receipt_count).toBe(2)
    expect(combined?.approvals.validated_requests).toBe(1)
    expect(combined?.provenance_truncated).toBe(true)
  })
  it('renders one timeline event with multiple source receipts and a keyboard-accessible detail button', () => {
    render(
      <EventTimeline
        events={[event]}
        nativeCommands={parseNativeEvidenceSummary(summary).commands}
      />,
    )
    expect(screen.getAllByText('toy command')).toHaveLength(1)
    expect(
      screen.getByText(/Source live-source, position 3/),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/Source rollout-source, position 1/),
    ).toBeInTheDocument()
    const toggle = screen.getByRole('button', {
      name: 'Expand Tool Call details',
    })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(toggle)
    expect(
      screen.getByRole('button', { name: 'Collapse Tool Call details' }),
    ).toHaveAttribute('aria-expanded', 'true')
  })

  it('drops raw evidence and preserves inherited and approval audit counts separately', () => {
    const parsed = parseNativeEvidenceSummary({
      ...summary,
      raw: 'secret',
      commands: [
        {
          ...summary.commands[0],
          command: 'secret',
          receipts: [{ ...summary.commands[0].receipts[0], payload: 'secret' }],
        },
      ],
      approvals: { ...summary.approvals, decision: 'secret' },
    })
    expect(JSON.stringify(parsed)).not.toContain('secret')
    expect(parsed.inherited_receipt_count).toBe(2)
    expect(parsed.commands).toHaveLength(1)
    expect(parsed.approvals.cleared_requests).toBe(0)
    expect(() =>
      parseNativeEvidenceSummary({ ...summary, inherited_receipt_count: -1 }),
    ).toThrow('incompatible')
  })
})
