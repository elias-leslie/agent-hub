'use client'

import { ErrorPage } from '@/components/error'

export default function MemoryError({
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
      title="Failed to load memory"
      message="Unable to fetch memory data. The memory service might be unavailable."
      label="Memory"
    />
  )
}
