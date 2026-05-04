import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { PromptRevisionHistory } from '@/app/prompts/[slug]/components/PromptRevisionHistory'
import type { Prompt, PromptRevision } from '@/lib/api/prompts'

const prompt: Prompt = {
  id: 1,
  slug: 'persona-heartbeat-instructions',
  name: 'Persona heartbeat instructions',
  content: 'Current content',
  description: 'Current description',
  is_global: false,
  enabled: true,
  exclude_agents: [],
  owner_agent_slug: 'persona',
  prompt_type: 'persona_heartbeat_instructions',
  deletion_locked: false,
  created_at: '2026-03-10T12:00:00Z',
  updated_at: '2026-03-11T12:00:00Z',
}

const revisions: PromptRevision[] = [
  {
    id: 'rev-current',
    prompt_id: 1,
    prompt_slug: prompt.slug,
    prompt_name: prompt.name,
    action: 'update',
    content: 'Current content',
    description: 'Current description',
    is_global: false,
    enabled: true,
    exclude_agents: [],
    owner_agent_id: 27,
    prompt_type: 'persona_heartbeat_instructions',
    deletion_locked: false,
    content_hash: 'abcdef1234567890',
    changed_by: 'api',
    change_reason: 'Latest benchmark promote',
    created_at: '2026-03-11T12:00:00Z',
  },
  {
    id: 'rev-old',
    prompt_id: 1,
    prompt_slug: prompt.slug,
    prompt_name: prompt.name,
    action: 'update',
    content: 'Older content',
    description: 'Older description',
    is_global: false,
    enabled: true,
    exclude_agents: [],
    owner_agent_id: 27,
    prompt_type: 'persona_heartbeat_instructions',
    deletion_locked: false,
    content_hash: '1234567890abcdef',
    changed_by: 'api',
    change_reason: 'Previous state',
    created_at: '2026-03-10T12:00:00Z',
  },
]

describe('PromptRevisionHistory', () => {
  it('marks the matching revision as the current state', () => {
    render(
      <PromptRevisionHistory
        prompt={prompt}
        revisions={revisions}
        isLoading={false}
        restoringRevisionId={null}
        onRestore={vi.fn()}
      />,
    )

    expect(screen.getAllByText('Current state')).toHaveLength(1)
    expect(screen.getByText('Latest benchmark promote')).toBeInTheDocument()
  })

  it('requires confirmation before restoring a revision', () => {
    const onRestore = vi.fn()

    render(
      <PromptRevisionHistory
        prompt={prompt}
        revisions={revisions}
        isLoading={false}
        restoringRevisionId={null}
        onRestore={onRestore}
      />,
    )

    const restoreButtons = screen.getAllByRole('button', { name: 'Restore' })
    fireEvent.click(restoreButtons[1])
    expect(
      screen.getByRole('button', { name: 'Confirm Restore' }),
    ).toBeInTheDocument()
    expect(onRestore).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: 'Confirm Restore' }))
    expect(onRestore).toHaveBeenCalledWith('rev-old')
  })
})
