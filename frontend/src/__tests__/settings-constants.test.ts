import { describe, expect, it } from 'vitest'

import {
  buildSettingsProviders,
  DEFAULT_PROVIDER_COLOR,
  filterVisibleSettingsProviders,
  getProviderApiFamily,
  getProviderColor,
  getProviderInfo,
  isOAuthProvider,
  PROVIDER_COLORS,
} from '@/components/settings/constants'

// Live provider ids from /api/models `providers` (2026-10-09).
const LIVE_PROVIDERS = [
  'claude',
  'cloudflare',
  'codex',
  'gemini',
  'local',
  'nvidia',
  'typesafe',
  'xai',
]

const API_FAMILIES = [
  'anthropic-messages',
  'claude-code-cli',
  'google-generative-ai',
  'openai-codex-responses',
  'openai-completions',
]

describe('settings provider constants', () => {
  it('treats Gemini as an API-key provider', () => {
    expect(isOAuthProvider('gemini')).toBe(false)
    expect(getProviderInfo('gemini')).toMatchObject({
      id: 'gemini',
      name: 'Gemini',
      hint: 'Google AI API key',
    })
  })

  it('filters internal provider rows out of the settings screen', () => {
    expect(
      filterVisibleSettingsProviders([
        'gemini',
        'cloudcode',
        'antigravity',
        '_system_internal',
      ]),
    ).toEqual(['gemini'])
  })

  it('builds cards from live catalog providers and flags credential-only ones as retired', () => {
    const entries = buildSettingsProviders(LIVE_PROVIDERS, [
      'gemini',
      'openrouter',
      'kimi-code',
    ])
    const ids = entries.map((entry) => entry.id)

    expect(ids).not.toContain('claude')
    for (const family of API_FAMILIES) expect(ids).not.toContain(family)
    expect(entries.find((e) => e.id === 'gemini')).toEqual({
      id: 'gemini',
      retired: false,
    })
    expect(entries.find((e) => e.id === 'openrouter')).toEqual({
      id: 'openrouter',
      retired: true,
    })
    expect(entries.find((e) => e.id === 'kimi-code')?.retired).toBe(true)
    expect(ids).not.toContain('openai')
  })

  it('marks retired provider info as delete-only and keeps live labels', () => {
    expect(getProviderInfo('openrouter', { retired: true })).toMatchObject({
      id: 'openrouter',
      retired: true,
    })
    expect(getProviderInfo('nvidia', { displayName: 'NVIDIA' }).name).toBe(
      'NVIDIA NIM',
    )
    expect(getProviderInfo('typesafe').retired).toBeUndefined()
  })

  it('maps provider ids to the API family that reports their health', () => {
    expect(getProviderApiFamily('gemini')).toBe('google-generative-ai')
    expect(getProviderApiFamily('codex')).toBe('openai-codex-responses')
    expect(getProviderApiFamily('xai')).toBe('openai-completions')
    expect(getProviderApiFamily('openrouter')).toBeUndefined()
  })
})

describe('provider colors', () => {
  it('covers every live provider, including claude in amber', () => {
    for (const id of LIVE_PROVIDERS) expect(PROVIDER_COLORS[id]).toBeDefined()
    expect(PROVIDER_COLORS.claude).toMatchObject({
      dot: 'bg-amber-400',
      chart: '#f59e0b',
    })
  })

  it('holds no retired provider colors', () => {
    expect(Object.keys(PROVIDER_COLORS).sort()).toEqual(
      [...LIVE_PROVIDERS].sort(),
    )
  })

  it('falls back to the default color for unknown providers', () => {
    expect(getProviderColor('unknown')).toBe(DEFAULT_PROVIDER_COLOR)
  })
})
