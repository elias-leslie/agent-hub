'use client'

import { X } from 'lucide-react'
import type { ModelOption } from '@/components/chat/use-models'
import {
  CapabilitiesMatrix,
  CompositeScore,
  ContextWindow,
  CostComparison,
  RemoveButtons,
  ScoreBreakdown,
} from './model-comparison-sections'
import { ModelRadar } from './model-radar'

interface ModelComparisonProps {
  models: ModelOption[]
  onClose: () => void
  onRemoveModel: (modelId: string) => void
}

export function ModelComparison({
  models,
  onClose,
  onRemoveModel,
}: ModelComparisonProps) {
  if (models.length === 0) return null

  return (
    <div className="fixed inset-y-0 right-0 w-full lg:w-[800px] bg-slate-900 border-l border-slate-800 shadow-2xl z-50 overflow-y-auto">
      {/* Header */}
      <div className="sticky top-0 z-10 bg-slate-900 border-b border-slate-800 px-6 py-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-bold text-slate-100">
              Model Comparison
            </h2>
            <p className="text-xs text-slate-400 mt-0.5">
              {models.length} model{models.length !== 1 ? 's' : ''} selected
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-2 rounded-lg hover:bg-slate-800 transition-colors"
            aria-label="Close comparison"
          >
            <X className="h-5 w-5 text-slate-500" />
          </button>
        </div>
      </div>

      <div className="p-6 space-y-8">
        {/* Radar Chart Overlay */}
        <div className="bg-slate-800/50 rounded-lg p-6 border border-slate-700">
          <h3 className="text-sm font-semibold text-slate-100 mb-4">
            Capability Comparison
          </h3>
          <ModelRadar models={models} size="lg" />
        </div>

        <ScoreBreakdown models={models} />
        <CompositeScore models={models} />
        <CostComparison models={models} />
        <ContextWindow models={models} />
        <CapabilitiesMatrix models={models} />
        <RemoveButtons models={models} onRemoveModel={onRemoveModel} />
      </div>
    </div>
  )
}
