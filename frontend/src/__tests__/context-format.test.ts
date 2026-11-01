import { describe, expect, it } from 'vitest'
import {
  cellGroup,
  isStale,
  roleLabel,
  signedPct,
  signedTok,
  tok,
} from '../app/context/format'

describe('context format helpers', () => {
  it('shows unknown as an em dash, never 0', () => {
    expect(tok(null)).toBe('—')
    expect(signedTok(undefined)).toBe('—')
    expect(signedPct(null)).toBe('—')
    expect(tok(0)).toBe('0')
  })

  it('formats tokens and signed moves', () => {
    expect(tok(47_900)).toBe('47.9K')
    expect(tok(122_000)).toBe('122K')
    expect(signedTok(-21_000)).toBe('−21.0K')
    expect(signedPct(12.4)).toBe('+12%')
  })

  it('groups cells and labels roles', () => {
    expect(cellGroup('implementation')).toBe('roles')
    expect(cellGroup('subagent:general-purpose')).toBe('subagents')
    expect(cellGroup('agent:neri')).toBe('agents')
    expect(cellGroup('unknown')).toBe('other')
    expect(roleLabel('subagent:general-purpose')).toBe('general-purpose')
    expect(roleLabel('review')).toBe('Review')
  })

  it('calls a cell stale after three days without a start', () => {
    const now = Date.parse('2026-11-01T12:00:00Z')
    expect(isStale({ latest_at: '2026-10-31T12:00:00Z' }, now)).toBe(false)
    expect(isStale({ latest_at: '2026-10-27T12:00:00Z' }, now)).toBe(true)
  })
})
