'use client'

import { AlertCircle, Check } from 'lucide-react'
import { cn } from '@/lib/utils'

export function SaveFlash({
  saving,
  error,
}: {
  saving: boolean
  error: boolean
}) {
  if (!saving && !error) return null
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium',
        'animate-pulse',
        error
          ? 'bg-red-900/30 text-red-400'
          : 'bg-emerald-900/30 text-emerald-400',
      )}
    >
      {error ? (
        <>
          <AlertCircle className="h-3 w-3" /> Error
        </>
      ) : (
        <>
          <Check className="h-3 w-3" /> Saved
        </>
      )}
    </span>
  )
}
