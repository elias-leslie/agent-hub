import { BarChart3 } from 'lucide-react'
import { SkeletonCard, SkeletonSection } from './analytics-components'

export function LoadingState() {
  return (
    <div className="p-4 space-y-4 overflow-auto">
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-6 gap-3">
        <SkeletonCard />
        <SkeletonCard />
        <SkeletonCard />
        <SkeletonCard />
        <SkeletonCard />
        <SkeletonCard />
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        <SkeletonSection />
        <SkeletonSection />
        <SkeletonSection />
      </div>
      <SkeletonSection />
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <SkeletonSection />
        <SkeletonSection />
      </div>
    </div>
  )
}

interface ErrorStateProps {
  message: string
}

export function ErrorState({ message }: ErrorStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-24 text-center">
      <div className="p-4 rounded-full bg-red-900/20 mb-4">
        <BarChart3 className="w-8 h-8 text-red-400" />
      </div>
      <h3 className="text-lg font-medium text-slate-100 mb-1">
        Failed to Load Analytics
      </h3>
      <p className="text-sm text-red-400 max-w-sm">{message}</p>
    </div>
  )
}
