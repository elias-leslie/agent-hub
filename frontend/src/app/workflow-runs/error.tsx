'use client'

import { ErrorPage } from '@/components/error'

export default function WorkflowRunsError({
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
      title="Could not show workflow runs"
      message="The page failed to render. Retry; if it keeps failing, the run data may be malformed."
      label="Workflow runs"
    />
  )
}
