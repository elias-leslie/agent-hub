'use client'

import { AlertTriangle } from 'lucide-react'
import { ErrorPage } from '@/components/error'

export default function DashboardError({
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
      title="Failed to load dashboard"
      message="Unable to fetch dashboard data. This might be a temporary issue with the backend."
      icon={AlertTriangle}
      label="Dashboard"
    />
  )
}
