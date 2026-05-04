'use client'

import { Brain } from 'lucide-react'
import { useRouter, useSearchParams } from 'next/navigation'
import { Suspense, useCallback, useMemo } from 'react'
import { type MemoryTabId, MemoryTabs } from '@/components/memory/MemoryTabs'
import { AnalyticsTab } from '@/components/memory/tabs/AnalyticsTab'
import { CaptureTab } from '@/components/memory/tabs/CaptureTab'
import { EpisodesTab } from '@/components/memory/tabs/EpisodesTab'
import { SessionsTab } from '@/components/memory/tabs/SessionsTab'
import { useMemory } from '@/hooks/use-memory'
import { CATEGORY_CONFIG } from '@/lib/memory-config'
import { cn } from '@/lib/utils'

function MemoryPageContent() {
  const router = useRouter()
  const searchParams = useSearchParams()

  const activeTab = (searchParams.get('tab') as MemoryTabId) || 'episodes'

  const handleTabChange = useCallback(
    (tab: MemoryTabId) => {
      const params = new URLSearchParams(searchParams.toString())
      if (tab === 'episodes') {
        params.delete('tab')
      } else {
        params.set('tab', tab)
      }
      const qs = params.toString()
      router.push(qs ? `/memory?${qs}` : '/memory', { scroll: false })
    },
    [router, searchParams],
  )

  return (
    <div className="flex flex-col h-[calc(100vh-56px)]">
      <MemoryTabs activeTab={activeTab} onTabChange={handleTabChange} />
      {activeTab === 'episodes' && <EpisodesTab />}
      {activeTab === 'sessions' && <SessionsTab />}
      {activeTab === 'capture' && <CaptureTab />}
      {activeTab === 'analytics' && <AnalyticsTab />}
    </div>
  )
}

function LoadingState() {
  return (
    <div className="flex h-[calc(100vh-56px)]">
      <div className="flex-1 p-4">
        <div className="animate-pulse space-y-4">
          <div className="h-10 bg-slate-700 rounded-lg" />
          <div className="space-y-2">
            {Array.from({ length: 8 }).map((_, i) => (
              <div key={i} className="h-12 bg-slate-700 rounded" />
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

export default function MemoryPage() {
  const { stats, isLoadingStats } = useMemory({})

  const categoryStats = useMemo(() => {
    if (!stats?.by_category) return []
    return stats.by_category.slice(0, 4)
  }, [stats])

  return (
    <div className="page-shell">
      <header className="sticky top-0 z-30 border-b border-slate-800/80 bg-slate-900/90 backdrop-blur-xl">
        <div className="px-6 lg:px-8">
          <div className="flex items-center justify-between h-12">
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2.5">
                <Brain className="w-5 h-5 text-emerald-400" />
                <h1 className="text-base font-semibold text-slate-100 tracking-tight">
                  Memory
                </h1>
              </div>

              <div className="hidden sm:flex items-center gap-3 text-xs font-mono tabular-nums">
                <span className="text-slate-400">
                  {isLoadingStats ? '...' : (stats?.total ?? 0)} total
                </span>
                {categoryStats.length > 0 && (
                  <>
                    <span className="text-slate-600">|</span>
                    {categoryStats.map((cat) => (
                      <span
                        key={cat.category}
                        className={cn(
                          'flex items-center gap-1',
                          CATEGORY_CONFIG[cat.category].color,
                        )}
                      >
                        {CATEGORY_CONFIG[cat.category].icon}
                        {cat.count}
                      </span>
                    ))}
                  </>
                )}
              </div>
            </div>
          </div>
        </div>
      </header>

      <Suspense fallback={<LoadingState />}>
        <MemoryPageContent />
      </Suspense>
    </div>
  )
}
