'use client'

import { AlertTriangle } from 'lucide-react'
import { ErrorPage } from '@/components/error'

export default function TokenShareError({
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
      title="Token share could not load"
      message="Try again."
      icon={AlertTriangle}
      buttonColor="bg-amber-600 hover:bg-amber-500"
      label="Token share"
    />
  )
}
