'use client'

import { AlertTriangle } from 'lucide-react'
import { ErrorPage } from '@/components/error'

export default function AdminError({
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
      title="Failed to load admin panel"
      message="Unable to fetch kill switch data. Please try again."
      icon={AlertTriangle}
      buttonColor="bg-amber-600 hover:bg-amber-500"
      label="Admin"
    />
  )
}
