import { Gauge } from 'lucide-react'
import type { MemoryBudgetUsage } from '@/lib/api/memory-settings'

export function BudgetUsageDisplay({
  usage,
  continuityEnabled,
}: {
  usage: MemoryBudgetUsage
  continuityEnabled?: boolean
}) {
  return (
    <div className="space-y-2 p-3 rounded-lg bg-slate-800/50">
      <div className="flex items-center gap-2 text-sm font-medium text-slate-300">
        <Gauge className="w-4 h-4" />
        Current Usage
      </div>
      <div className="space-y-1.5 text-sm">
        <div className="flex justify-between items-center">
          <span className="text-slate-500">Mandates</span>
          <div className="text-right">
            <span className="font-mono text-slate-300">
              {usage.mandates_injected}/{usage.mandates_total}
            </span>
            {usage.mandates_total - usage.mandates_injected > 0 && (
              <span className="ml-2 text-xs text-amber-400">
                {usage.mandates_total - usage.mandates_injected} cut
              </span>
            )}
          </div>
        </div>
        <div className="flex justify-between items-center">
          <span className="text-slate-500">Guardrails</span>
          <div className="text-right">
            <span className="font-mono text-slate-300">
              {usage.guardrails_injected}/{usage.guardrails_total}
            </span>
            {usage.guardrails_total - usage.guardrails_injected > 0 && (
              <span className="ml-2 text-xs text-amber-400">
                {usage.guardrails_total - usage.guardrails_injected} cut
              </span>
            )}
          </div>
        </div>
        <div className="flex justify-between items-center">
          <span className="text-slate-500">References</span>
          <div className="text-right">
            <span className="font-mono text-slate-300">
              {usage.reference_injected}/{usage.reference_total}
            </span>
          </div>
        </div>
        <div className="flex justify-between items-center">
          <span className="text-slate-500">Continuity</span>
          <div className="text-right">
            <span className="font-mono text-slate-300">
              {continuityEnabled !== false
                ? usage.continuity_tokens > 0
                  ? `${usage.continuity_tokens} tokens`
                  : '0 sessions'
                : 'Off'}
            </span>
          </div>
        </div>
        <div className="pt-1.5 border-t border-slate-700">
          <div className="flex justify-between font-medium">
            <span className="text-slate-300">Tokens</span>
            <span className="font-mono text-slate-300">
              {usage.total_tokens.toLocaleString()}
            </span>
          </div>
          <div className="flex justify-between text-xs text-slate-500 mt-1">
            <span>Coverage</span>
            <span>
              {Math.round(
                ((usage.mandates_injected + usage.guardrails_injected) /
                  Math.max(usage.mandates_total + usage.guardrails_total, 1)) *
                  100,
              )}
              % of mandates/guardrails
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}
