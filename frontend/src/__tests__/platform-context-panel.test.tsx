import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { PlatformContextPanel } from '@/components/PlatformContextPanel'
import type { Prompt } from '@/lib/api/prompts'
import { createQueryClientWrapper } from './test-utils'

const apiMocks = vi.hoisted(() => ({
  fetchOptionalPrompt: vi.fn(),
  updatePrompt: vi.fn(),
  createPrompt: vi.fn(),
}))

vi.mock('@/lib/api/prompts', () => ({
  PLATFORM_CONTEXT_PROMPT_SLUG: 'platform-context',
  fetchOptionalPrompt: apiMocks.fetchOptionalPrompt,
  updatePrompt: apiMocks.updatePrompt,
  createPrompt: apiMocks.createPrompt,
}))

const storedPrompt: Prompt = {
  id: 7,
  slug: 'platform-context',
  name: 'Platform Context',
  content: 'Stored platform context line',
  description: 'Platform-wide context',
  is_global: true,
  enabled: true,
  exclude_agents: [],
  owner_agent_slug: null,
  prompt_type: 'platform_context',
  deletion_locked: false,
  created_at: '2026-09-01T12:00:00Z',
  updated_at: '2026-09-02T12:00:00Z',
}

function renderPanel() {
  const Wrapper = createQueryClientWrapper()
  return render(
    <Wrapper>
      <PlatformContextPanel activeAgentCount={3} />
    </Wrapper>,
  )
}

describe('PlatformContextPanel', () => {
  beforeEach(() => {
    apiMocks.fetchOptionalPrompt.mockReset()
    apiMocks.updatePrompt.mockReset()
    apiMocks.createPrompt.mockReset()
  })

  it('shows the stored content after a slow load and keeps Save disabled until edited', async () => {
    let resolvePrompt: (value: Prompt) => void = () => {}
    apiMocks.fetchOptionalPrompt.mockReturnValue(
      new Promise<Prompt>((resolve) => {
        resolvePrompt = resolve
      }),
    )

    renderPanel()
    resolvePrompt(storedPrompt)

    const header = await screen.findByText('Stored platform context line')
    fireEvent.click(header)

    const editor = screen.getByRole('textbox')
    expect(editor).toHaveValue('Stored platform context line')
    expect(screen.getByRole('button', { name: /save/i })).toBeDisabled()

    fireEvent.change(editor, { target: { value: 'Updated context' } })
    const save = screen.getByRole('button', { name: /save/i })
    expect(save).toBeEnabled()

    apiMocks.updatePrompt.mockResolvedValue({
      ...storedPrompt,
      content: 'Updated context',
    })
    fireEvent.click(save)

    await waitFor(() =>
      expect(apiMocks.updatePrompt).toHaveBeenCalledWith('platform-context', {
        content: 'Updated context',
      }),
    )
    expect(apiMocks.createPrompt).not.toHaveBeenCalled()
  })
})
