'use client'

import {
  Check,
  ChevronDown,
  ChevronUp,
  Eye,
  MessageCircle,
  ThumbsDown,
  ThumbsUp,
  Trash2,
} from 'lucide-react'
import { useState } from 'react'
import type { MemoryEpisode } from '@/lib/memory-api'
import { cn } from '@/lib/utils'

interface MemoryCardProps {
  episode: MemoryEpisode
  isSelected: boolean
  onSelect: () => void
  onDelete: () => void
  isDeleting: boolean
}

function formatDate(dateStr: string): string {
  const date = new Date(dateStr)
  return date.toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function getCategoryBadge(category: string): {
  icon: string
  color: string
  label: string
} {
  const badges: Record<string, { icon: string; color: string; label: string }> =
    {
      coding_standard: {
        icon: '📏',
        color: 'bg-blue-900/30 text-amber-300',
        label: 'Standard',
      },
      troubleshooting_guide: {
        icon: '⚠️',
        color: 'bg-red-900/30 text-red-300',
        label: 'Gotcha',
      },
      system_design: {
        icon: '🏗️',
        color: 'bg-purple-900/30 text-purple-300',
        label: 'Design',
      },
      operational_context: {
        icon: '⚙️',
        color: 'bg-amber-900/30 text-amber-300',
        label: 'Ops',
      },
      domain_knowledge: {
        icon: '📚',
        color: 'bg-emerald-900/30 text-emerald-300',
        label: 'Domain',
      },
      active_state: {
        icon: '▶️',
        color: 'bg-cyan-900/30 text-cyan-300',
        label: 'Active',
      },
    }
  return (
    badges[category] || {
      icon: '📝',
      color: 'bg-slate-800 text-slate-400',
      label: category,
    }
  )
}

function getScopeBadge(scope: string): { color: string; label: string } {
  const badges: Record<string, { color: string; label: string }> = {
    global: { color: 'bg-indigo-900/30 text-indigo-300', label: 'Global' },
    project: { color: 'bg-teal-900/30 text-teal-300', label: 'Project' },
    task: { color: 'bg-orange-900/30 text-orange-300', label: 'Task' },
  }
  return badges[scope] || { color: 'bg-slate-800 text-slate-400', label: scope }
}

function getUtilityScoreColor(score: number | undefined): string {
  if (score === undefined) return 'bg-slate-800 text-slate-400'
  if (score >= 0.7) return 'bg-emerald-900/30 text-emerald-300'
  if (score >= 0.4) return 'bg-amber-900/30 text-amber-300'
  return 'bg-red-900/30 text-red-300'
}

export function MemoryCard({
  episode,
  isSelected,
  onSelect,
  onDelete,
  isDeleting,
}: MemoryCardProps) {
  const [isExpanded, setIsExpanded] = useState(false)
  const categoryBadge = getCategoryBadge(episode.category)
  const scopeBadge = getScopeBadge(episode.scope)

  // Truncate content for preview
  const previewContent =
    episode.content.length > 200
      ? `${episode.content.slice(0, 200)}...`
      : episode.content

  return (
    <div
      className={cn(
        'rounded-lg border transition-all',
        'bg-slate-900/50',
        isSelected
          ? 'border-emerald-400 ring-1 ring-emerald-500/50'
          : 'border-slate-800 hover:border-slate-700',
      )}
      data-testid="memory-card"
    >
      {/* Header */}
      <div className="flex items-start gap-3 p-4">
        {/* Checkbox */}
        <button
          onClick={onSelect}
          className={cn(
            'flex-shrink-0 w-5 h-5 rounded border transition-colors mt-0.5',
            isSelected
              ? 'bg-emerald-500 border-emerald-500 text-white'
              : 'border-slate-600 hover:border-emerald-400',
          )}
        >
          {isSelected && <Check className="w-4 h-4" />}
        </button>

        {/* Content */}
        <div className="flex-1 min-w-0">
          {/* Meta row */}
          <div className="flex items-center gap-2 flex-wrap mb-2">
            <span
              className={cn(
                'px-2 py-0.5 rounded-full text-xs font-medium',
                scopeBadge.color,
              )}
            >
              {scopeBadge.label}
            </span>
            <span
              className={cn(
                'px-2 py-0.5 rounded-full text-xs font-medium',
                categoryBadge.color,
              )}
            >
              {categoryBadge.icon} {categoryBadge.label}
            </span>
            <span className="text-xs text-slate-500">
              {formatDate(episode.created_at)}
            </span>
            <span className="text-xs text-slate-500 px-2 py-0.5 rounded bg-slate-800">
              {episode.source}
            </span>
          </div>

          {/* Content preview or full */}
          <p className="text-sm text-slate-300 whitespace-pre-wrap">
            {isExpanded ? episode.content : previewContent}
          </p>

          {/* Expand/collapse */}
          {episode.content.length > 200 && (
            <button
              onClick={() => setIsExpanded(!isExpanded)}
              className="flex items-center gap-1 mt-2 text-xs text-emerald-400 hover:underline"
            >
              {isExpanded ? (
                <>
                  <ChevronUp className="w-3 h-3" /> Show less
                </>
              ) : (
                <>
                  <ChevronDown className="w-3 h-3" /> Show more
                </>
              )}
            </button>
          )}

          {/* Usage stats row (compact) */}
          {(episode.loaded_count !== undefined ||
            episode.utility_score !== undefined) && (
            <div className="flex items-center gap-3 mt-2 text-xs text-slate-400">
              {episode.loaded_count !== undefined && (
                <span
                  className="flex items-center gap-1"
                  title="Times loaded into context"
                >
                  <Eye className="w-3 h-3" />
                  {episode.loaded_count}
                </span>
              )}
              {episode.referenced_count !== undefined && (
                <span
                  className="flex items-center gap-1"
                  title="Times cited by LLM"
                >
                  <MessageCircle className="w-3 h-3" />
                  {episode.referenced_count}
                </span>
              )}
              {episode.helpful_count !== undefined &&
                episode.helpful_count > 0 && (
                  <span
                    className="flex items-center gap-1 text-emerald-400"
                    title="Helpful feedback"
                  >
                    <ThumbsUp className="w-3 h-3" />
                    {episode.helpful_count}
                  </span>
                )}
              {episode.harmful_count !== undefined &&
                episode.harmful_count > 0 && (
                  <span
                    className="flex items-center gap-1 text-red-400"
                    title="Harmful feedback"
                  >
                    <ThumbsDown className="w-3 h-3" />
                    {episode.harmful_count}
                  </span>
                )}
              {episode.utility_score !== undefined && (
                <span
                  className={cn(
                    'px-1.5 py-0.5 rounded text-xs font-medium',
                    getUtilityScoreColor(episode.utility_score),
                  )}
                  title="Utility score (cited vs loaded ratio)"
                >
                  {(episode.utility_score * 100).toFixed(0)}%
                </span>
              )}
            </div>
          )}
        </div>

        {/* Delete button */}
        <button
          onClick={onDelete}
          disabled={isDeleting}
          className={cn(
            'flex-shrink-0 p-2 rounded-lg transition-colors',
            'text-slate-400 hover:text-red-500 hover:bg-red-900/20',
            isDeleting && 'opacity-50 cursor-not-allowed',
          )}
          title="Delete memory"
        >
          {isDeleting ? (
            <div className="w-4 h-4 border-2 border-slate-400 border-t-transparent rounded-full animate-spin" />
          ) : (
            <Trash2 className="w-4 h-4" />
          )}
        </button>
      </div>
    </div>
  )
}
