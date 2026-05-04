'use client'

import { ErrorPage } from '@/components/error'

export default function SessionsError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  return (
    <ErrorPage
      error={error}
      reset={reset}
      title="Failed to load sessions"
      message="Unable to fetch session data. Please check your connection and try again."
      label="Sessions"
    />
  )
}
