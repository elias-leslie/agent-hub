import { describe, expect, it } from 'vitest'

import { normalizeThinkingLevel } from '@/components/chat/chat-panel'

describe('normalizeThinkingLevel', () => {
  it('drops display/default values that the backend rejects', () => {
    expect(normalizeThinkingLevel('default')).toBeNull()
    expect(normalizeThinkingLevel('')).toBeNull()
    expect(normalizeThinkingLevel(null)).toBeNull()
  })

  it('keeps backend-supported thinking levels', () => {
    expect(normalizeThinkingLevel('minimal')).toBe('minimal')
    expect(normalizeThinkingLevel('low')).toBe('low')
    expect(normalizeThinkingLevel('medium')).toBe('medium')
    expect(normalizeThinkingLevel('high')).toBe('high')
    expect(normalizeThinkingLevel('ultrathink')).toBe('ultrathink')
  })
})
