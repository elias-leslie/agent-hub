import { describe, expect, it } from 'vitest'

import {
  filterVisibleSettingsProviders,
  getProviderInfo,
  isOAuthProvider,
  listKnownProviderIds,
} from '@/components/settings/constants'

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

  it('only exposes supported providers in the known provider list', () => {
    expect(listKnownProviderIds()).toContain('gemini')
    expect(listKnownProviderIds()).not.toContain('antigravity')
  })
})
