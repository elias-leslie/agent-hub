'use client'

import { ErrorPage } from '@/components/error'

export default function ChatError({
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
      title="Chat unavailable"
      message="Failed to initialize chat. Please try again."
      label="Chat"
    />
  )
}
