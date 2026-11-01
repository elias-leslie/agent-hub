import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ContextHttpError } from '@/lib/api/context-http'
import { dayLabel, kindLabel } from '../format'
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

describe('plain labels', () => {
  it('shows a calendar day as that day and block kinds without internal ids', () => {
    expect(dayLabel('2026-10-29')).toBe('Oct 29')
    expect(kindLabel('global_guardrail')).toBe('guardrail')
    expect(kindLabel('some_new_kind')).toBe('some new kind')
  })
})
