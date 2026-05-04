import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { ChildRunCard } from '@/app/persona/components/workspace-cards'

describe('workspace card keyboard controls', () => {
  it('toggles persona run cards from Enter and Space while staying focusable', () => {
    const onToggle = vi.fn()

    render(
      <ChildRunCard
        entry={
          {
            id: 'child-run-1',
            entry_type: 'child_run',
            timestamp: '2026-04-22T09:30:00Z',
            session_id: 'sess-child-1',
            parent_session_id: 'sess-root-1',
            project_id: 'agent-hub',
            agent_slug: 'coder',
            session_type: 'completion',
            status: 'completed',
            role: null,
            content: null,
            summary_oneliner: 'Proof summary',
            display_summary: 'Proof summary',
            current_branch: null,
            external_id: 'task-123',
            model: 'codex/gpt-5.4',
            live_summary: null,
            live_status: null,
            message_count: 1,
            tool_count: 0,
            event_previews: [],
            issue_markers: [],
            pulse_tags: [],
            primary_pulse_tag: null,
            root_causes: [],
            primary_root_cause: null,
            pulse_summary: null,
          } as never
        }
        activeIssueTag={null}
        selected={false}
        expanded={false}
        onToggle={onToggle}
      />,
    )

    const card = screen.getByRole('button')
    expect(card).toHaveAttribute('tabindex', '0')

    fireEvent.keyDown(card, { key: 'Enter' })
    fireEvent.keyDown(card, { key: ' ' })

    expect(onToggle).toHaveBeenCalledTimes(2)
  })
})
