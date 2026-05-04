'use client'

import { ErrorPage } from '@/components/error'

export default function AgentsError({
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
      title="Failed to load agents"
      message="Unable to fetch agent configuration. Please check your connection and try again."
      label="Agents"
    />
  )
}
