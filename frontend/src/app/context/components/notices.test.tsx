import { act, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ContextHttpError } from '@/lib/api/context-http'
import { dayLabel, kindLabel, markerText } from '../format'
import { FailedNotice } from './Notices'

describe('FailedNotice', () => {
  it('says owner access is needed on a 403, the same way for every page', () => {
    render(
      <FailedNotice
        what="the changes"
        error={new ContextHttpError(403, 'Loading changes')}
        hasData={false}
        onRetry={() => {}}
      />,
    )
    expect(screen.getByRole('alert')).toHaveTextContent(
      "Couldn't load the changes: owner access is needed.",
    )
    expect(screen.getByRole('alert')).not.toHaveTextContent('403')
  })

  it('keeps the plain reason for other failures', () => {
    render(
      <FailedNotice
        what="the trend"
        error={new ContextHttpError(500)}
        hasData
        updatedAt={Date.now()}
        onRetry={() => {}}
      />,
    )
    expect(screen.getByRole('alert')).toHaveTextContent(
      "Couldn't refresh the trend (Agent Hub answered 500). Showing the last data",
    )
  })
})

describe('FailedNotice age', () => {
  afterEach(() => vi.useRealTimers())

  it('ages the loaded time while the banner stays on screen', () => {
    vi.useFakeTimers()
    render(
      <FailedNotice
        what="the trend"
        error={new ContextHttpError(500)}
        hasData
        updatedAt={Date.now()}
        onRetry={() => {}}
      />,
    )
    expect(screen.getByRole('alert')).toHaveTextContent('loaded just now')
    act(() => {
      vi.advanceTimersByTime(5 * 60_000)
    })
    expect(screen.getByRole('alert')).toHaveTextContent('loaded 5m ago')
  })
})

describe('plain labels', () => {
  it('names a config marker by what changed, not by its hash', () => {
    expect(markerText({ kind: 'config', label: '0468bf28' })).toBe(
      'request shape changed',
    )
    expect(markerText({ kind: 'harness_version', label: '2.1.317' })).toBe(
      'new version 2.1.317',
    )
    expect(markerText({ kind: 'memory', label: 'learning' })).toBe(
      'memory: learning',
    )
  })

  it('shows a calendar day as that day and block kinds without internal ids', () => {
    expect(dayLabel('2026-10-29')).toBe('Oct 29')
    expect(kindLabel('global_guardrail')).toBe('guardrail')
    expect(kindLabel('some_new_kind')).toBe('some new kind')
  })
})
