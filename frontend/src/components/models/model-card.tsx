'use client'

import {
  Brain,
  Camera,
  Clock,
  Database,
  Eye,
  FileText,
  Gauge,
  Headphones,
  Pencil,
  Zap,
} from 'lucide-react'
import type { ModelOption } from '@/components/chat/use-models'
import { PROVIDER_COLORS } from '@/components/settings/constants'
import { formatCatalogModelPricing } from '@/lib/model-pricing'
import { cn } from '@/lib/utils'
import { ModelRadar } from './model-radar'

interface ModelCardProps {
  model: ModelOption
  isSelected?: boolean
  onSelect?: (model: ModelOption) => void
  onExpand?: (model: ModelOption) => void
}

function getSpeedBadgeColor(tier: string): string {
  switch (tier) {
    case 'fast':
      return 'bg-green-500/10 text-green-400 border-green-500/20'
    case 'medium':
      return 'bg-amber-500/10 text-amber-400 border-amber-500/20'
    case 'slow':
      return 'bg-red-500/10 text-red-400 border-red-500/20'
    default:
      return 'bg-slate-500/10 text-slate-400 border-slate-500/20'
  }
}

function formatSyncMoment(value: string | null | undefined): string | null {
  if (!value) return null
  return new Date(value).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function ModelCard({
  model,
  isSelected,
  onSelect,
  onExpand,
}: ModelCardProps) {
  const providerColor = PROVIDER_COLORS[model.provider]
  const hasEnrichment = !!model.enrichment
  const pricing = formatCatalogModelPricing(model)
  const syncedAt = formatSyncMoment(model.enrichment?.synced_at)
  const isCodexOnlyPreview = model.availability === 'codex_only'

  return (
    <div
      className={cn(
        'group relative rounded-lg border bg-slate-900 overflow-hidden',
        'transition-all duration-200',
        isSelected
          ? 'border-amber-500/40 shadow-lg shadow-amber-500/10 ring-2 ring-amber-500/20'
          : 'border-slate-800 hover:border-slate-700 hover:shadow-md',
      )}
      onClick={() => onExpand?.(model)}
    >
      {/* Provider accent */}
      <div
        className={cn(
          'absolute top-0 left-0 right-0 h-1',
          providerColor.dot.replace('bg-', 'bg-gradient-to-r from-'),
        )}
      />

      <div className="p-5">
        {/* Header */}
        <div className="flex items-start justify-between mb-3">
          <div className="flex-1 min-w-0">
            <div className="flex items-start gap-1.5">
              <h3
                className="text-base font-semibold leading-tight text-slate-100"
                title={model.name}
              >
                {model.name}
              </h3>
              {hasEnrichment && (
                <Database className="mt-1 h-3 w-3 text-emerald-500 flex-shrink-0" />
              )}
            </div>
            <p
              className="mt-0.5 line-clamp-2 text-xs leading-tight text-slate-400"
              title={model.alias}
            >
              {model.alias}
              {model.family && (
                <span className="ml-1 text-slate-400">({model.family})</span>
              )}
            </p>
            {isCodexOnlyPreview && (
              <div className="mt-2 inline-flex rounded-full border border-emerald-400/20 bg-emerald-400/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-emerald-200">
                ChatGPT/Codex now, API soon
              </div>
            )}
          </div>

          {/* Provider badge */}
          <div
            className={cn(
              'flex items-center gap-1.5 px-2 py-1 rounded-md text-xs font-medium border ml-2',
              providerColor.dot.replace('bg-', 'text-'),
              providerColor.bg,
            )}
          >
            <div
              className={cn('w-1.5 h-1.5 rounded-full', providerColor.dot)}
            />
            <span className="capitalize">{model.provider}</span>
          </div>
        </div>

        {/* Composite Score */}
        <div className="flex items-center gap-2 mb-4">
          <div className="flex-1">
            <div className="text-xs text-slate-400 mb-1">Composite Score</div>
            <div className="flex items-baseline gap-1">
              <span className="text-2xl font-bold text-slate-100">
                {model.scores.composite}
              </span>
              <span className="text-xs text-slate-400">/100</span>
            </div>
          </div>

          {/* Cost & Speed */}
          <div className="flex min-w-[150px] flex-col gap-2">
            <div className="rounded-xl border border-slate-800 bg-slate-950/80 px-3 py-2 text-right">
              <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">
                Pricing
              </div>
              <div className="mt-1 text-sm font-semibold text-slate-100">
                {pricing.primary}
              </div>
              <div className="text-[11px] text-slate-400">
                {pricing.secondary}
              </div>
            </div>
            <div
              className={cn(
                'px-2 py-1 rounded text-xs font-medium text-center border',
                getSpeedBadgeColor(model.speed_tier),
              )}
            >
              {model.speed_tier === 'fast' && (
                <Zap className="inline h-3 w-3 mr-0.5" />
              )}
              {model.speed_tier === 'medium' && (
                <Gauge className="inline h-3 w-3 mr-0.5" />
              )}
              {model.speed_tier === 'slow' && (
                <Clock className="inline h-3 w-3 mr-0.5" />
              )}
              {model.speed_tier}
            </div>
          </div>
        </div>

        {/* Radar Chart */}
        <div className="mb-4 -mx-2">
          <ModelRadar models={[model]} size="sm" />
        </div>

        {/* Capabilities */}
        <div className="flex flex-wrap items-center gap-1.5 mb-3">
          {model.capabilities.has_vision && (
            <div
              className="flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] bg-blue-500/10 text-amber-400 border border-blue-500/20"
              title="Vision"
            >
              <Eye className="h-2.5 w-2.5" />
              Vision
            </div>
          )}
          {model.capabilities.has_thinking && (
            <div
              className="flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] bg-violet-500/10 text-violet-400 border border-violet-500/20"
              title="Extended Thinking"
            >
              <Brain className="h-2.5 w-2.5" />
              Thinking
            </div>
          )}
          {model.capabilities.can_generate_images && (
            <div
              className="flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] bg-purple-500/10 text-purple-400 border border-purple-500/20"
              title="Image Generation"
            >
              <Camera className="h-2.5 w-2.5" />
              Image
            </div>
          )}
          {model.capabilities.supports_pdf && (
            <div
              className="flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] bg-orange-500/10 text-orange-400 border border-orange-500/20"
              title="PDF Processing"
            >
              <FileText className="h-2.5 w-2.5" />
              PDF
            </div>
          )}
          {model.capabilities.supports_audio && (
            <div
              className="flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] bg-teal-500/10 text-teal-400 border border-teal-500/20"
              title="Audio Input"
            >
              <Headphones className="h-2.5 w-2.5" />
              Audio
            </div>
          )}
          {model.capabilities.can_edit_images && (
            <div
              className="flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] bg-pink-500/10 text-pink-400 border border-pink-500/20"
              title="Image Editing"
            >
              <Pencil className="h-2.5 w-2.5" />
              Edit
            </div>
          )}
        </div>

        {/* Context Window & Timeout */}
        <div className="text-xs text-slate-400 border-t border-slate-800 pt-3 space-y-1.5">
          <div className="flex justify-between">
            <span>Context Window</span>
            <span className="font-mono font-medium text-slate-300">
              {(model.context_window / 1000).toFixed(0)}K
            </span>
          </div>
          <div className="flex justify-between gap-3">
            <span>Price Source</span>
            <span
              className={cn(
                'rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.16em]',
                model.cost.source === 'enrichment'
                  ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-200'
                  : 'border-slate-700 bg-slate-800 text-slate-300',
              )}
            >
              {pricing.source}
            </span>
          </div>
          {syncedAt && (
            <div className="flex justify-between">
              <span>Last Refresh</span>
              <span className="text-slate-300">{syncedAt}</span>
            </div>
          )}
        </div>

        {/* Compare button */}
        {onSelect && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              onSelect(model)
            }}
            className={cn(
              'absolute top-3 right-3 opacity-0 group-hover:opacity-100 transition-opacity',
              'px-2 py-1 rounded-md text-xs font-medium border',
              isSelected
                ? 'bg-amber-500 text-slate-950 border-amber-400'
                : 'bg-slate-800 text-slate-300 border-slate-700 hover:bg-slate-700',
            )}
          >
            {isSelected ? 'Selected' : 'Compare'}
          </button>
        )}
      </div>
    </div>
  )
}
