import { fireEvent, render, screen } from '@testing-library/react'
import type { ComponentPropsWithoutRef } from 'react'
import { describe, expect, it, vi } from 'vitest'

import { AgentActionsMenu } from '@/app/agents/components/AgentActionsMenu'
import { AgentsTable } from '@/app/agents/components/AgentsTable'
import type { Agent } from '@/app/agents/lib/types'

vi.mock('next/link', () => ({
  default: ({
    href,
    children,
    ...props
  }: ComponentPropsWithoutRef<'a'> & { href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}))

const baseAgent: Agent = {
  id: 1,
  slug: 'builder',
  name: 'Builder',
  description: 'Builds things',
  primary_model_id: 'gpt-5.4',
  fallback_models: [],
  temperature: 0.2,
  is_active: true,
  is_coding_agent: true,
  timeout_seconds: 60,
  version: 3,
  created_at: '2026-03-01T00:00:00Z',
  updated_at: '2026-03-02T00:00:00Z',
}

describe('agent browser UI', () => {
  it('uses the chat route from the row actions menu', () => {
    render(
      <AgentActionsMenu
        agent={baseAgent}
        onClone={vi.fn()}
        onArchive={vi.fn()}
      />,
    )

    fireEvent.click(
      screen.getByRole('button', { name: /open actions for builder/i }),
    )

    expect(screen.getByRole('menuitem', { name: 'Chat' })).toHaveAttribute(
      'href',
      '/agents/builder/chat',
    )
  })

  it('explains how to recover from an empty filtered state', () => {
    render(
      <AgentsTable
        agents={[]}
        sortField="name"
        sortDirection="asc"
        onSort={vi.fn()}
        getMetrics={() => null}
        onClone={vi.fn()}
        onArchive={vi.fn()}
        totalAgents={4}
        searchQuery="missing"
        showInactive={false}
        onClearSearch={vi.fn()}
        onShowActiveOnly={vi.fn()}
      />,
    )

    expect(screen.getByText('No agents match "missing"')).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Clear search' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Include inactive agents' }),
    ).toBeInTheDocument()
  })
})
