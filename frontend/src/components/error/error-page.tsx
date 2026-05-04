'use client'

import type { LucideIcon } from 'lucide-react'
import { AlertCircle, RefreshCw } from 'lucide-react'
import { useEffect } from 'react'

interface ErrorPageProps {
  error: Error & { digest?: string }
  reset: () => void
  title?: string
  message?: string
  icon?: LucideIcon
  iconColor?: string
  buttonColor?: string
  label?: string
}

export function ErrorPage({
  error,
  reset,
  title = 'Something went wrong',
  message = 'An unexpected error occurred. Please try again.',
  icon: Icon = AlertCircle,
  iconColor = 'text-red-500',
  buttonColor = 'bg-amber-500 hover:bg-amber-400',
  label = 'Error',
}: ErrorPageProps) {
  useEffect(() => {
    console.error(`${label} error:`, error)
  }, [error, label])

  return (
    <div className="flex flex-col items-center justify-center py-20">
      <div className="p-4 rounded-full bg-red-900/20 mb-4">
        <Icon className={`h-8 w-8 ${iconColor}`} />
      </div>
      <h2 className="text-lg font-semibold text-slate-100 mb-2">{title}</h2>
      <p className="text-sm text-slate-400 mb-6 text-center max-w-md">
        {message}
      </p>
      <button
        onClick={reset}
        className={`flex items-center gap-2 px-4 py-2 rounded-xl ${buttonColor} text-slate-950 font-semibold transition-colors cursor-pointer`}
      >
        <RefreshCw className="h-4 w-4" />
        Try again
      </button>
    </div>
  )
}
