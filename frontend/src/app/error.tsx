"use client"

import { useEffect } from "react"
import { AlertCircle, RefreshCw, Home } from "lucide-react"
import Link from "next/link"

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    console.error("Application error:", error)
  }, [error])

  return (
    <div className="min-h-screen bg-slate-950 flex items-center justify-center p-6">
      <div className="max-w-md w-full text-center">
        <div className="mb-6">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-red-100 dark:bg-red-900/30">
            <AlertCircle className="w-8 h-8 text-red-400" />
          </div>
        </div>

        <h1 className="text-2xl font-bold text-slate-100 mb-2">
          Something went wrong
        </h1>

        <p className="text-slate-400 mb-6">
          An unexpected error occurred. Please try again or return to the
          dashboard.
        </p>

        {error.digest && (
          <p className="text-xs text-slate-500 dark:text-slate-500 mb-6 font-mono">
            Error ID: {error.digest}
          </p>
        )}

        <div className="flex flex-col sm:flex-row gap-3 justify-center">
          <button
            onClick={reset}
            className="inline-flex items-center justify-center gap-2 px-4 py-2 rounded-lg bg-amber-600 hover:bg-amber-500 text-white font-medium transition-colors"
          >
            <RefreshCw className="w-4 h-4" />
            Try again
          </button>

          <Link
            href="/dashboard"
            className="inline-flex items-center justify-center gap-2 px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-300 dark:hover:bg-slate-700 text-slate-100 font-medium transition-colors"
          >
            <Home className="w-4 h-4" />
            Go to Dashboard
          </Link>
        </div>
      </div>
    </div>
  )
}
