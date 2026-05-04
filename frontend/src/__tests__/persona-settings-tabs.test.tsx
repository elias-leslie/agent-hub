import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { PersonaAutosaveState } from '@/app/persona/hooks/usePersona'
import { IdentityTab } from '@/app/persona/settings/components/IdentityTab'
import { PersonaSettingsHeader } from '@/app/persona/settings/components/PersonaSettingsHeader'
import { SessionLimitsTab } from '@/app/persona/settings/components/SessionLimitsTab'
import { VoiceHeartbeatTab } from '@/app/persona/settings/components/VoiceHeartbeatTab'
import type { Persona } from '@/types/persona'

const mockPreviewVoice = vi.fn()
const mockSetSelectedVoice = vi.fn()
const mockSetTtsEnabled = vi.fn()
const mockHeartbeatStatus = vi.fn()

vi.mock('@/lib/api-config', () => ({
  buildApiUrl: (path: string) => path,
  fetchApi: vi.fn(),
  getApiBaseUrl: () => '',
}))

vi.mock('@agent-hub/chat-ui', () => ({
  useVoicePreferences: () => ({
    voices: [
      {
        id: 'voice-1',
        name: 'Aria',
        locale: 'en-US',
        gender: 'Female',
        personalities: ['Warm', 'Clear'],
      },
      {
        id: 'voice-2',
        name: 'Guy',
        locale: 'en-US',
        gender: 'Male',
        personalities: ['Calm'],
      },
    ],
    selectedVoice: 'voice-1',
    ttsEnabled: false,
    setSelectedVoice: mockSetSelectedVoice,
    setTtsEnabled: mockSetTtsEnabled,
    previewVoice: mockPreviewVoice,
  }),
}))

vi.mock('@/app/persona/hooks/useHeartbeat', () => ({
  useHeartbeat: () => ({
    status: mockHeartbeatStatus(),
    trigger: vi.fn(),
    isTriggering: false,
  }),
}))

vi.mock('next/link', () => ({
  default: ({ href, children, ...props }: any) => (
    <a
      href={typeof href === 'string' ? href : (href?.pathname ?? '#')}
      {...props}
    >
      {children}
    </a>
  ),
}))

import { fetchApi } from '@/lib/api-config'

function jsonResponse(data: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: vi.fn().mockResolvedValue(data),
  } as unknown as Response
}

const basePersona: Persona = {
  id: 1,
  name: 'Persona',
  personality: 'Helpful',
  user_profile: null,
  heartbeat_instructions: 'Check systems',
  user_context: 'Prefers brevity',
  voice_id: 'voice-1',
  voice_enabled: false,
  heartbeat_interval_minutes: 60,
  execution_state: 'active',
  avatar_url: null,
  greeting: 'Hello',
  onboarding_complete: true,
  onboarding_phase: 'complete',
  onboarding_attempts: 2,
  session_reset_mode: 'off',
  session_reset_hour: 9,
  session_reset_idle_minutes: 120,
  limits: null,
  agent_slug: 'persona',
  version: 1,
  updated_at: null,
}

const idleAutosave: PersonaAutosaveState = {
  status: 'idle',
  errorMessage: null,
  savedAt: null,
}

describe('persona settings tabs', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.useFakeTimers()
    mockHeartbeatStatus.mockReturnValue({
      running: false,
      last_run: null,
      elapsed_seconds: null,
      interval_minutes: 60,
      runtime: {
        model: 'claude-opus-4-6',
        provider: 'claude',
        model_display_name: 'Claude Opus 4.6',
        thinking_level: 'medium',
        supports_tools: true,
        supports_thinking: true,
        supports_verbosity: false,
        supports_session_cache: false,
        heartbeat_supported: true,
        warnings: [],
      },
    })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('resets onboarding and refreshes persona state', async () => {
    const onPersonaRefresh = vi.fn()
    vi.mocked(fetchApi).mockResolvedValueOnce(
      jsonResponse({
        ...basePersona,
        onboarding_phase: 'not_started',
        onboarding_complete: false,
      }),
    )

    render(
      <IdentityTab
        persona={basePersona}
        onUpdate={vi.fn()}
        onPersonaRefresh={onPersonaRefresh}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /reset/i }))

    await act(async () => {
      await Promise.resolve()
    })

    expect(fetchApi).toHaveBeenCalledWith('/api/persona/reset-onboarding', {
      method: 'POST',
    })
    expect(onPersonaRefresh).toHaveBeenCalledWith(
      expect.objectContaining({
        onboarding_phase: 'not_started',
        onboarding_complete: false,
      }),
    )
  })

  it('updates heartbeat interval and voice selection', async () => {
    const onUpdate = vi.fn()

    render(
      <VoiceHeartbeatTab
        persona={basePersona}
        onUpdate={onUpdate}
        autosave={idleAutosave}
      />,
    )

    fireEvent.change(screen.getByLabelText('Heartbeat interval'), {
      target: { value: '120' },
    })
    expect(onUpdate).toHaveBeenCalledWith({ heartbeat_interval_minutes: 120 })

    fireEvent.click(screen.getByRole('button', { name: 'Select voice Guy' }))
    expect(mockSetSelectedVoice).toHaveBeenCalledWith('voice-2')
    expect(screen.getByText('Claude Opus 4.6')).toBeInTheDocument()
    expect(screen.getByText('Tools: supported')).toBeInTheDocument()
  })

  it('updates structured user profile fields from identity settings', () => {
    const onUpdate = vi.fn()

    render(<IdentityTab persona={basePersona} onUpdate={onUpdate} />)

    fireEvent.change(screen.getByLabelText('Timezone'), {
      target: { value: 'America/Chicago' },
    })

    expect(onUpdate).toHaveBeenCalledWith({
      user_profile: {
        timezone: 'America/Chicago',
      },
    })
  })

  it('filters voices and previews the selected sample', () => {
    render(
      <VoiceHeartbeatTab
        persona={basePersona}
        onUpdate={vi.fn()}
        autosave={idleAutosave}
      />,
    )

    fireEvent.change(screen.getByPlaceholderText('Search voices...'), {
      target: { value: 'guy' },
    })

    expect(screen.getByText('Guy')).toBeInTheDocument()
    expect(screen.queryByText('Aria')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Preview voice Guy' }))
    expect(mockPreviewVoice).toHaveBeenCalledWith('voice-2')
  })

  it('updates session reset mode, timing, and custom limits', () => {
    const onUpdate = vi.fn()

    const { rerender } = render(
      <SessionLimitsTab
        persona={{
          ...basePersona,
          session_reset_mode: 'daily',
          limits: { max_turns: 300 },
        }}
        onUpdate={onUpdate}
      />,
    )

    fireEvent.change(screen.getByLabelText('Session reset hour'), {
      target: { value: '11' },
    })
    expect(onUpdate).toHaveBeenCalledWith({ session_reset_hour: 11 })

    fireEvent.click(screen.getByRole('button', { name: 'Idle' }))
    expect(onUpdate).toHaveBeenCalledWith({ session_reset_mode: 'idle' })

    rerender(
      <SessionLimitsTab
        persona={{
          ...basePersona,
          session_reset_mode: 'idle',
          session_reset_idle_minutes: 120,
          limits: { max_turns: 300 },
        }}
        onUpdate={onUpdate}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: '30 min' }))
    expect(onUpdate).toHaveBeenCalledWith({ session_reset_idle_minutes: 30 })

    fireEvent.change(screen.getByLabelText('Max turns'), {
      target: { value: '350' },
    })
    expect(onUpdate).toHaveBeenCalledWith({ limits: { max_turns: 350 } })

    fireEvent.click(screen.getByRole('button', { name: /reset/i }))
    expect(onUpdate).toHaveBeenCalledWith({ limits: null })
  })

  it('rejects non-positive max-turn updates in the settings UI', () => {
    const onUpdate = vi.fn()

    render(<SessionLimitsTab persona={basePersona} onUpdate={onUpdate} />)

    fireEvent.change(screen.getByLabelText('Max turns'), {
      target: { value: '0' },
    })

    expect(onUpdate).not.toHaveBeenCalled()
  })

  it('shows reset onboarding failures inline', async () => {
    vi.mocked(fetchApi).mockResolvedValueOnce(
      jsonResponse({ detail: 'failed' }, 500),
    )

    render(
      <IdentityTab
        persona={basePersona}
        onUpdate={vi.fn()}
        onPersonaRefresh={vi.fn()}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /reset/i }))

    await act(async () => {
      await Promise.resolve()
    })

    expect(screen.getByText('Reset failed with status 500')).toBeInTheDocument()
  })

  it('shows heartbeat warnings when runtime is incompatible or disabled', () => {
    mockHeartbeatStatus.mockReturnValue({
      running: false,
      last_run: null,
      elapsed_seconds: null,
      interval_minutes: 0,
      runtime: {
        model: 'codex/gpt-5.1-codex-mini',
        provider: 'codex',
        model_display_name: null,
        thinking_level: 'medium',
        supports_tools: false,
        supports_thinking: false,
        supports_verbosity: false,
        supports_session_cache: false,
        heartbeat_supported: false,
        warnings: [
          'Heartbeat requires tool execution, but codex/gpt-5.1-codex-mini does not support tools.',
        ],
      },
    })

    render(
      <VoiceHeartbeatTab
        persona={{ ...basePersona, heartbeat_interval_minutes: 0 }}
        onUpdate={vi.fn()}
        autosave={idleAutosave}
      />,
    )

    expect(
      screen.getByText(
        'Heartbeat is currently off, so Persona is not autonomously driving work.',
      ),
    ).toBeInTheDocument()
    expect(
      screen.getByText(
        'Heartbeat requires tool execution, but codex/gpt-5.1-codex-mini does not support tools.',
      ),
    ).toBeInTheDocument()
    expect(screen.getByText('Tools: not supported')).toBeInTheDocument()
  })

  it('links Persona settings back to Arena', () => {
    render(
      <PersonaSettingsHeader
        personaName="Avery"
        hasChanges={false}
        isSaving={false}
        saveSuccess={false}
        saveError={false}
        onSave={vi.fn()}
      />,
    )

    expect(screen.getByTitle('Open Avery Arena')).toHaveAttribute(
      'href',
      '/persona/arena',
    )
  })
})
