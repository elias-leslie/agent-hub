import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { SessionEfficiency } from '@/app/admin/components/SessionEfficiency'
import { SessionRow } from '@/app/sessions/components/SessionRow'
import { parseActivityCost } from '@/lib/api/activity-cost'
import type { SessionListItem } from '@/lib/api/sessions'
import snapshot from './fixtures/session-efficiency-snapshot.json'

const row: SessionListItem = {
  id: '01a16619-0000-4000-8000-000000000000',
  project_id: 'agent-hub',
  provider: 'opencode-go',
  model: 'opencode-go/deepseek-v4.1-flash',
  status: 'completed',
  agent_slug: null,
  session_type: 'pi',
  message_count: 3,
  total_input_tokens: 0,
  total_output_tokens: 0,
  created_at: '2026-10-22T12:00:00Z',
  updated_at: '2026-10-22T12:05:00Z',
  request_errors: {
    count: 4,
    last_category: 'request_timeout',
    last_message: 'Request timed out.',
  },
}

describe('failed request badge', () => {
  it('flags a completed session whose requests failed, with the last category', () => {
    render(
      <SessionRow
        session={row}
        isCursor={false}
        isSelected={false}
        onClick={() => {}}
      />,
    )
    const badge = screen.getByTestId('request-errors')
    expect(badge).toHaveTextContent('4 failed')
    expect(badge).toHaveAttribute(
      'title',
      '4 failed requests. Last: request timeout – Request timed out.',
    )
  })

  it('shows nothing when no request failed', () => {
    render(
      <SessionRow
        session={{ ...row, request_errors: null }}
        isCursor={false}
        isSelected={false}
        onClick={() => {}}
      />,
    )
    expect(screen.queryByTestId('request-errors')).not.toBeInTheDocument()
  })

  it('appears on the session efficiency review row', () => {
    const activity = parseActivityCost(snapshot)
    if (!activity) throw new Error('Missing synthetic session fixture')
    render(<SessionEfficiency activity={activity} />)
    expect(screen.getByTestId('request-errors')).toHaveTextContent('2 failed')
    expect(
      screen.getByText(
        /2 failed requests · Last: request timeout – Request timed out\./,
      ),
    ).toBeInTheDocument()
  })
})
