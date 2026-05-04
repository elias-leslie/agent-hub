'use client'

import { Copy, Loader2 } from 'lucide-react'
import { useState } from 'react'
import type { SimilarEpisode } from '@/lib/memory-api'
import { fetchSimilarEpisodes } from '@/lib/memory-api'
import { cn } from '@/lib/utils'

interface SimilarEpisodesListProps {
  episodeUuid: string
}

export function SimilarEpisodesList({ episodeUuid }: SimilarEpisodesListProps) {
  const [showSimilar, setShowSimilar] = useState(false)
  const [similar, setSimilar] = useState<SimilarEpisode[] | null>(null)
  const [isLoadingSimilar, setIsLoadingSimilar] = useState(false)

  const handleLoadSimilar = async () => {
    if (similar !== null) {
      setShowSimilar(!showSimilar)
      return
    }
    setIsLoadingSimilar(true)
    setShowSimilar(true)
    try {
      const data = await fetchSimilarEpisodes(episodeUuid)
      setSimilar(data.similar)
    } catch {
      setSimilar([])
    } finally {
      setIsLoadingSimilar(false)
    }
  }

  return (
    <>
      <button
        onClick={(e) => {
          e.stopPropagation()
          handleLoadSimilar()
        }}
        className={cn(
          'flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs font-medium border transition-colors',
          showSimilar
            ? 'bg-purple-900/20 text-purple-400 border-purple-800'
            : 'bg-slate-800/50 text-slate-400 border-slate-700 hover:text-purple-400',
        )}
      >
        {isLoadingSimilar ? (
          <Loader2 className="h-3 w-3 animate-spin" />
        ) : (
          <Copy className="h-3 w-3" />
        )}
        Similar {similar !== null && `(${similar.length})`}
      </button>

      {showSimilar && similar !== null && (
        <div className="rounded-lg border border-slate-700 bg-slate-800/50 overflow-hidden">
          {similar.length === 0 ? (
            <p className="p-3 text-xs text-slate-400 italic">
              No similar episodes found
            </p>
          ) : (
            <div className="divide-y divide-slate-700/50">
              {similar.map((s) => (
                <div key={s.uuid} className="px-3 py-2 space-y-1">
                  <div className="flex items-center justify-between">
                    <code className="text-[10px] font-mono text-slate-500">
                      {s.uuid.slice(0, 8)}
                    </code>
                    <span
                      className={cn(
                        'text-[10px] font-mono font-medium',
                        s.relevance_score >= 0.9
                          ? 'text-red-500'
                          : s.relevance_score >= 0.8
                            ? 'text-amber-500'
                            : 'text-emerald-500',
                      )}
                    >
                      {(s.relevance_score * 100).toFixed(0)}% match
                    </span>
                  </div>
                  <p className="text-xs text-slate-300 line-clamp-2">
                    {s.content}
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </>
  )
}
