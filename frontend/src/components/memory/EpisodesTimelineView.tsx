'use client'

import { ChevronDown, ChevronRight, Inbox } from 'lucide-react'
import { useCallback, useMemo, useState } from 'react'
import { TimelineItem } from '@/components/memory/TimelineItem'
import type { MemoryEpisode } from '@/lib/memory-api'
import { TIMELINE_COLLAPSE_KEY } from '@/lib/memory-config'

type DateBucket =
  | 'today'
  | 'yesterday'
  | 'this_week'
  | 'last_week'
  | 'this_month'
  | 'last_month'
  | 'older'

interface DateGroup {
  label: string
  key: DateBucket
  episodes: MemoryEpisode[]
}

const BUCKET_ORDER: DateBucket[] = [
  'today',
  'yesterday',
  'this_week',
  'last_week',
  'this_month',
  'last_month',
  'older',
]

function classifyDate(
  dateStr: string,
  now: Date,
): { label: string; key: DateBucket } {
  const date = new Date(dateStr)
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const episodeDate = new Date(
    date.getFullYear(),
    date.getMonth(),
    date.getDate(),
  )
  const delta = Math.floor((today.getTime() - episodeDate.getTime()) / 86400000)

  if (delta === 0) return { label: 'Today', key: 'today' }
  if (delta === 1) return { label: 'Yesterday', key: 'yesterday' }
  if (delta < 7 && episodeDate.getDay() < today.getDay())
    return { label: 'This Week', key: 'this_week' }
  if (delta < 7) return { label: 'Last Week', key: 'last_week' }
  if (
    episodeDate.getFullYear() === today.getFullYear() &&
    episodeDate.getMonth() === today.getMonth()
  )
    return { label: 'This Month', key: 'this_month' }
  if (delta < 60) return { label: 'Last Month', key: 'last_month' }
  return { label: 'Older', key: 'older' }
}

function DateGroupHeader({
  label,
  count,
  isOpen,
  onToggle,
}: {
  label: string
  count: number
  isOpen: boolean
  onToggle: () => void
}) {
  return (
    <button
      onClick={onToggle}
      className="flex items-center gap-2 group w-full text-left"
    >
      {isOpen ? (
        <ChevronDown className="h-4 w-4 text-slate-500 group-hover:text-slate-300 transition-colors" />
      ) : (
        <ChevronRight className="h-4 w-4 text-slate-500 group-hover:text-slate-300 transition-colors" />
      )}
      <span className="text-sm font-semibold text-slate-200 group-hover:text-slate-100 transition-colors">
        {label}
      </span>
      <span className="px-2 py-0.5 text-[10px] font-medium rounded-full bg-slate-800 text-slate-400 border border-slate-700">
        {count}
      </span>
      <div className="flex-1 h-px bg-slate-800 ml-2" />
    </button>
  )
}

interface EpisodesTimelineViewProps {
  items: MemoryEpisode[]
  isLoading: boolean
  isFetchingMore: boolean
}

export function EpisodesTimelineView({
  items,
  isLoading,
  isFetchingMore,
}: EpisodesTimelineViewProps) {
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(() => {
    try {
      const stored = localStorage.getItem(TIMELINE_COLLAPSE_KEY)
      return stored ? new Set(JSON.parse(stored) as string[]) : new Set()
    } catch {
      return new Set()
    }
  })

  const groups = useMemo((): DateGroup[] => {
    const now = new Date()
    const buckets: Record<
      string,
      { label: string; episodes: MemoryEpisode[] }
    > = {}

    for (const ep of items) {
      const { label, key } = classifyDate(ep.created_at, now)
      if (!buckets[key]) {
        buckets[key] = { label, episodes: [] }
      }
      buckets[key].episodes.push(ep)
    }

    return BUCKET_ORDER.filter((key) => buckets[key]).map((key) => ({
      label: buckets[key].label,
      key,
      episodes: buckets[key].episodes,
    }))
  }, [items])

  const toggleGroup = useCallback((dateKey: string) => {
    setCollapsedGroups((prev) => {
      const next = new Set(prev)
      if (next.has(dateKey)) {
        next.delete(dateKey)
      } else {
        next.add(dateKey)
      }
      localStorage.setItem(TIMELINE_COLLAPSE_KEY, JSON.stringify([...next]))
      return next
    })
  }, [])

  if (isLoading) {
    return (
      <div className="p-6 space-y-8 animate-pulse">
        {[1, 2, 3].map((group) => (
          <div key={group} className="space-y-4">
            <div className="flex items-center gap-3">
              <div className="h-5 w-24 bg-slate-800 rounded" />
              <div className="h-5 w-8 bg-slate-800 rounded-full" />
            </div>
            <div className="ml-1.5 space-y-4">
              {[1, 2].map((item) => (
                <div key={item} className="flex gap-4">
                  <div className="flex flex-col items-center">
                    <div className="w-3 h-3 rounded-full bg-slate-700 mt-1.5" />
                    <div className="w-px flex-1 bg-slate-800" />
                  </div>
                  <div className="flex-1 rounded-lg bg-slate-800/50 border border-slate-800 p-3 space-y-2">
                    <div className="flex gap-2">
                      <div className="h-4 w-16 bg-slate-700 rounded" />
                      <div className="h-4 w-12 bg-slate-700 rounded" />
                    </div>
                    <div className="h-4 w-3/4 bg-slate-800 rounded" />
                    <div className="h-4 w-1/2 bg-slate-800 rounded" />
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    )
  }

  if (groups.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-24 text-center">
        <div className="p-4 rounded-full bg-slate-800 mb-4">
          <Inbox className="w-8 h-8 text-slate-500" />
        </div>
        <h3 className="text-lg font-medium text-slate-100 mb-1">
          No episodes yet
        </h3>
        <p className="text-sm text-slate-400 max-w-sm">
          Episodes will appear here grouped by date as they are captured.
        </p>
      </div>
    )
  }

  return (
    <div className="p-4 lg:p-6 space-y-6 max-w-3xl">
      {groups.map((group) => {
        const isOpen = !collapsedGroups.has(group.key)
        return (
          <div key={group.key}>
            <DateGroupHeader
              label={group.label}
              count={group.episodes.length}
              isOpen={isOpen}
              onToggle={() => toggleGroup(group.key)}
            />
            {isOpen && (
              <div className="mt-3 ml-1">
                {group.episodes.map((ep, idx) => (
                  <TimelineItem
                    key={ep.uuid}
                    episode={ep}
                    isLast={idx === group.episodes.length - 1}
                  />
                ))}
              </div>
            )}
          </div>
        )
      })}
      {isFetchingMore && (
        <div className="flex justify-center py-4">
          <div className="w-5 h-5 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
        </div>
      )}
    </div>
  )
}
