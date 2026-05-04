import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { AgentPreviewPanel } from '@/app/agents/[slug]/components/AgentPreviewPanel'
import type { AgentPreview, PreviewScenario } from '@/app/agents/[slug]/types'

const preview: AgentPreview = {
  slug: 'persona',
  name: 'Persona',
  combined_prompt: '<system>system only</system>',
  full_context: '<system>system only</system>\n\n<task>Do the heartbeat</task>',
  memory_query: 'heartbeat project state',
  memory_debug: {
    total_tokens: 1800,
    tier_counts: { L1: 2, L2: 1 },
    render_chars_saved: 640,
    memory_plan: [
      {
        uuid: '12345678-aaaa',
        block: 'mandate',
        tier: 'L1',
        reason: 'query_hit',
        summary: 'Use preview first',
        full_tokens: 40,
        rendered_tokens: 22,
      },
    ],
  },
  loaded_memory_uuids: ['12345678-aaaa', '87654321-bbbb'],
  reference_uuids: ['87654321-bbbb'],
  mandate_count: 2,
  guardrail_count: 1,
  mandate_uuids: ['12345678'],
  guardrail_uuids: ['87654321'],
  task_type: 'heartbeat',
  phase: null,
  project_id: 'agent-hub',
  task_prompt: 'Do the heartbeat',
  sections: [
    {
      label: 'Platform Context',
      source_kind: 'global_prompt',
      source_id: 'platform-context',
      placement: 'system',
      content_hash: 'abcd1234',
      chars: 32,
      estimated_tokens: 8,
      content: '<platform>db prompt</platform>',
      role: null,
      priority: null,
      updated_at: null,
    },
    {
      label: 'Task Prompt',
      source_kind: 'task_prompt',
      source_id: 'heartbeat',
      placement: 'user',
      content_hash: 'beef5678',
      chars: 17,
      estimated_tokens: 4,
      content: 'Do the heartbeat',
      role: null,
      priority: null,
      updated_at: null,
    },
  ],
}

const scenario: PreviewScenario = {
  projectId: 'agent-hub',
  phase: '',
  promptInput: '',
}

describe('AgentPreviewPanel', () => {
  it('renders scenario controls and memory debug details', () => {
    render(
      <AgentPreviewPanel
        preview={preview}
        previewMode="heartbeat"
        scenario={scenario}
        projectOptions={[{ id: 'agent-hub', name: 'Agent Hub' }]}
        showPreview={true}
        previewFetching={false}
        previewError={null}
        onPreviewModeChange={vi.fn()}
        onScenarioChange={vi.fn()}
        onTogglePreview={vi.fn()}
        onRefresh={vi.fn()}
      />,
    )

    expect(screen.getByText('Runtime Preview')).toBeInTheDocument()
    expect(screen.getByLabelText('Project Scope')).toBeInTheDocument()
    expect(
      screen.getByText(
        'Heartbeat preview builds the task prompt from live heartbeat inputs; only project and phase hints matter here.',
      ),
    ).toBeInTheDocument()
    expect(screen.getByText('Render Tiers')).toBeInTheDocument()
    expect(screen.getByText('L1 2')).toBeInTheDocument()
    expect(screen.getByText('Chars Saved')).toBeInTheDocument()
    expect(screen.getByText('640')).toBeInTheDocument()
    expect(screen.getByText('Tokens')).toBeInTheDocument()
    expect(screen.getByText('1,800')).toBeInTheDocument()
    expect(screen.getByText('Memory Plan')).toBeInTheDocument()
    expect(screen.getByText('Use preview first')).toBeInTheDocument()
    expect(screen.getByText('Platform Context')).toBeInTheDocument()
  })

  it('warns when chat preview would use an empty memory query', () => {
    render(
      <AgentPreviewPanel
        preview={undefined}
        previewMode="chat"
        scenario={{ projectId: '', phase: '', promptInput: '' }}
        projectOptions={[]}
        showPreview={false}
        previewFetching={false}
        previewError={null}
        onPreviewModeChange={vi.fn()}
        onScenarioChange={vi.fn()}
        onTogglePreview={vi.fn()}
        onRefresh={vi.fn()}
      />,
    )

    expect(
      screen.getByText(
        'Project scope is blank, so memory preview is using global-only scope.',
      ),
    ).toBeInTheDocument()
    expect(
      screen.getByText(
        'Chat preview has no user message yet, so the memory query will stay empty.',
      ),
    ).toBeInTheDocument()
    expect(screen.getByLabelText('User Message')).toBeInTheDocument()
  })
})
