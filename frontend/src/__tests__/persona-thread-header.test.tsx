import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { PersonaThreadHeader } from '@/app/persona/components/PersonaThreadHeader'

describe('PersonaThreadHeader', () => {
  it('shows compact persisted-thread context and keeps new-thread control in the lane row', () => {
    const onNewThread = vi.fn()

    render(
      <PersonaThreadHeader
        runtime={{
          primarySession: null,
          primarySessionDetails: null,
          activePersonaSessions: [],
          activeChildSessions: [],
          loading: false,
          error: null,
          stoppingSessionId: null,
          runtimeSyncKey: 'sync-1',
          refresh: vi.fn().mockResolvedValue(undefined),
          stopSession: vi.fn().mockResolvedValue(true),
          stopCurrentStream: vi.fn().mockResolvedValue(true),
          stopActiveWork: vi
            .fn()
            .mockResolvedValue({ cancelled: 0, attempted: 0 }),
        }}
        focusSession={{
          id: 'sess-1',
          project_id: 'summitflow',
          provider: 'codex',
          model: 'codex/gpt-5.4',
          status: 'completed',
          agent_slug: 'persona',
          session_type: 'chat',
          parent_session_id: null,
          external_id: null,
          current_branch: null,
          live_activity: {
            phase: 'completed',
            status: 'completed',
            summary: 'Session closed',
            health: 'completed',
            stalled: false,
            current_tool_name: null,
            last_tool_name: 'bash',
            outstanding_tool_calls: 0,
            tool_calls_count: 1,
            files_touched: [],
          },
          message_count: 4,
          total_input_tokens: 0,
          total_output_tokens: 0,
          created_at: '2026-04-15T23:44:07.068073Z',
          updated_at: '2026-04-15T23:48:07.970724Z',
        }}
        selectedSessionId="sess-1"
        targetProjectId="agent-hub"
        threadSource="session"
        onSelectSession={vi.fn()}
        activeTab="workflow"
        onOpenTab={vi.fn()}
        onNewThread={onNewThread}
        deskOpen
        onToggleDesk={vi.fn()}
      />,
    )

    expect(screen.getByText('summitflow')).toBeInTheDocument()
    expect(screen.getByText('Session closed')).toBeInTheDocument()
    expect(screen.getByText('bash')).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: /^Status$/i }),
    ).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /new thread/i }))
    expect(onNewThread).toHaveBeenCalledTimes(1)
  })
})
