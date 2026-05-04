'use client'

import { AlertCircle, Home, RefreshCw } from 'lucide-react'
import Link from 'next/link'
import { useEffect } from 'react'

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    console.error('Application error:', error)
  }, [error])

  return (
    <div className="flex min-h-screen items-center justify-center p-6">
      <div className="max-w-md w-full text-center animate-fade-up">
        <div className="mb-8">
          <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-2xl border border-red-500/20 bg-red-950/40 text-red-400">
            <AlertCircle className="w-7 h-7" />
          </div>
        </div>

        <h1 className="text-2xl font-bold tracking-tight text-slate-100 mb-3">
          Something went wrong
        </h1>

        <p className="text-sm text-slate-400 mb-6 max-w-xs mx-auto leading-relaxed">
          An unexpected error occurred. Please try again or return to the
          dashboard.
        </p>

        {error.digest && (
          <p className="text-xs text-slate-500 mb-6 font-mono">
            Error ID: {error.digest}
          </p>
        )}

        <div className="flex flex-col sm:flex-row gap-3 justify-center">
          <button onClick={reset} className="button-primary cursor-pointer">
            <RefreshCw className="w-4 h-4" />
            Try again
          </button>

          <Link href="/dashboard" className="button-secondary">
            <Home className="w-4 h-4" />
            Go to Dashboard
          </Link>
        </div>
      </div>
    </div>
  )
}
