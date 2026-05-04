import { fireEvent, render, screen } from '@testing-library/react'
import type { ComponentPropsWithoutRef } from 'react'
import { describe, expect, it, vi } from 'vitest'

import { AgentEditorHeader } from '@/app/agents/[slug]/components/AgentEditorHeader'
import { Sidebar } from '@/app/agents/[slug]/components/Sidebar'
import type { Agent } from '@/app/agents/[slug]/types'

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: vi.fn(),
  }),
}))

vi.mock('next/link', () => ({
  default: ({
    href,
    children,
    ...props
  }: ComponentPropsWithoutRef<'a'> & { href: string }) => (
    <a href={typeof href === 'string' ? href : ''} {...props}>
      {children}
    </a>
  ),
}))

const agent: Agent = {
  id: 1,
  slug: 'coder',
  name: 'Coder',
  description: 'Edits code',
  system_prompt: 'Prompt',
  primary_model_id: 'gpt-5.4',
  fallback_models: [],
  escalation_model_id: null,
  strategies: {},
  temperature: 0.2,
  thinking_level: 'medium',
  verbosity_level: 'medium',
  is_active: true,
  is_coding_agent: true,
  memory_config: null,
  effective_memory_config: {
    injection_enabled: true,
    project_index_enabled: true,
    tool_capabilities_enabled: true,
    include_mandates: true,
    include_guardrails: true,
    include_references: true,
    reference_index_enabled: true,
    continuity_enabled: true,
    continuity_max_sessions: 5,
    audience_tags: [],
    exclude_tags: [],
    exclude_memory_uuids: [],
  },
  max_concurrency: 4,
  max_subagent_concurrency: 2,
  daily_token_budget: 100000,
  hourly_request_limit: 30,
  timeout_seconds: 60,
  version: 4,
  created_at: '2026-03-01T00:00:00Z',
  updated_at: '2026-03-02T00:00:00Z',
}

describe('agent editor shell', () => {
  it('links the header chat and Arena actions to dedicated agent routes', () => {
    render(
      <AgentEditorHeader
        agent={agent}
        hasChanges={false}
        isSaving={false}
        onSave={vi.fn()}
        onPreview={vi.fn()}
        onOpenSidebar={vi.fn()}
        activeTabLabel="General"
      />,
    )

    expect(screen.getByRole('link', { name: 'Chat' })).toHaveAttribute(
      'href',
      '/agents/coder/chat',
    )
    expect(screen.getByRole('link', { name: 'Arena' })).toHaveAttribute(
      'href',
      '/arena/coder',
    )
    expect(
      screen.getByRole('button', { name: 'Back to agents' }),
    ).toBeInTheDocument()
  })

  it('shows the committee editor entry for the investment committee agent', () => {
    render(
      <Sidebar
        activeTab="general"
        agent={{
          ...agent,
          slug: 'investment-committee',
          name: 'Investment Committee',
        }}
        onTabChange={vi.fn()}
      />,
    )

    expect(
      screen.getByRole('button', { name: 'Committee' }),
    ).toBeInTheDocument()
  })

  it('closes the mobile sidebar after selecting a tab', () => {
    const onTabChange = vi.fn()
    const onMobileClose = vi.fn()

    render(
      <Sidebar
        activeTab="general"
        agent={agent}
        onTabChange={onTabChange}
        mobileOpen={true}
        onMobileClose={onMobileClose}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Models' }))

    expect(onTabChange).toHaveBeenCalledWith('models')
    expect(onMobileClose).toHaveBeenCalled()
  })
})
