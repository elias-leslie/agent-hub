'use client'

import { useEffect, useState } from 'react'
import { getApiBaseUrl } from '@/lib/api-config'

interface NarrationTag {
  id: number
  task_id: string
  session_id: string
  tag_type: string
  content: string
  created_at: string
}

interface NarrationTimelineResponse {
  task_id: string
  tags: NarrationTag[]
  total: number
}

const TAG_ICONS: Record<string, string> = {
  started: '▶',
  found: '🔍',
  modified: '✏',
  tested: '✓',
  confidence: '📊',
  blocked: '⛔',
  decision: '⚖',
}

const TAG_COLORS: Record<string, string> = {
  started: 'text-amber-400',
  found: 'text-yellow-400',
  modified: 'text-green-400',
  tested: 'text-emerald-400',
  confidence: 'text-purple-400',
  blocked: 'text-red-400',
  decision: 'text-orange-400',
}

export function NarrationTimeline({ taskId }: { taskId: string }) {
  const [tags, setTags] = useState<NarrationTag[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function fetchTags() {
      try {
        const res = await fetch(`${getApiBaseUrl()}/narration/tasks/${taskId}`)
        if (res.ok) {
          const data: NarrationTimelineResponse = await res.json()
          setTags(data.tags)
        }
      } catch {
        // Silently fail — narration is optional
      } finally {
        setLoading(false)
      }
    }
    fetchTags()
  }, [taskId])

  if (loading)
    return (
      <div className="text-xs text-muted-foreground">Loading narration...</div>
    )
  if (tags.length === 0) return null

  return (
    <div className="space-y-1">
      <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
        Progress Timeline
      </h4>
      <div className="space-y-0.5">
        {tags.map((tag) => (
          <div key={tag.id} className="flex items-start gap-2 text-xs">
            <span className="w-4 text-center flex-shrink-0">
              {TAG_ICONS[tag.tag_type] || '•'}
            </span>
            <span
              className={`font-mono ${TAG_COLORS[tag.tag_type] || 'text-muted-foreground'}`}
            >
              {tag.tag_type}
            </span>
            <span className="text-foreground/80 flex-1">{tag.content}</span>
            <span className="text-muted-foreground/50 flex-shrink-0">
              {new Date(tag.created_at).toLocaleTimeString(undefined, {
                hour: '2-digit',
                minute: '2-digit',
              })}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}
