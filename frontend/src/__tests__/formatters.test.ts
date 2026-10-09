import { describe, expect, it } from 'vitest'

import { formatModelName, formatUptime } from '@/lib/formatters'

describe('formatUptime', () => {
  it('shows minutes under an hour instead of 0h', () => {
    expect(formatUptime(30)).toBe('<1m')
    expect(formatUptime(155.6)).toBe('2m')
    expect(formatUptime(3599)).toBe('59m')
  })

  it('shows whole hours from one hour up', () => {
    expect(formatUptime(3600)).toBe('1h')
    expect(formatUptime(7 * 3600 + 120)).toBe('7h')
  })
})

describe('formatModelName', () => {
  it('shortens known provider prefixes', () => {
    expect(formatModelName('claude-opus-5-5')).toBe('opus-5-5')
    expect(formatModelName('gemini-3.1-flash', 20)).toBe('g-3.1-flash')
  })
})
