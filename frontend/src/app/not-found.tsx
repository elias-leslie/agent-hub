'use client'

import { ArrowLeft, FileQuestion, Home } from 'lucide-react'
import Link from 'next/link'

export default function NotFound() {
  return (
    <div className="flex min-h-screen items-center justify-center p-6">
      <div className="max-w-md w-full text-center animate-fade-up">
        <div className="mb-8">
          <div className="page-title-icon mx-auto !h-16 !w-16 !rounded-2xl">
            <FileQuestion className="w-7 h-7" />
          </div>
        </div>

        <h1 className="text-5xl font-bold tracking-tight text-slate-100 mb-3">
          404
        </h1>

        <h2 className="text-lg font-medium text-slate-400 mb-2">
          Page not found
        </h2>

        <p className="text-sm text-slate-500 mb-10 max-w-xs mx-auto leading-relaxed">
          The page you are looking for does not exist or has been moved.
        </p>

        <div className="flex flex-col sm:flex-row gap-3 justify-center">
          <Link href="/dashboard" className="button-primary">
            <Home className="w-4 h-4" />
            Go to Dashboard
          </Link>

          <button
            onClick={() =>
              typeof window !== 'undefined' && window.history.back()
            }
            className="button-secondary cursor-pointer"
          >
            <ArrowLeft className="w-4 h-4" />
            Go back
          </button>
        </div>
      </div>
    </div>
  )
}
