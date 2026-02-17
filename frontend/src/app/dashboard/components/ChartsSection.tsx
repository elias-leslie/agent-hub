import { Sparkline } from "@/components/dashboard/Sparkline";
import { ProviderStatusCard } from "@/components/dashboard/ProviderStatusCard";
import { formatCurrency, formatNumber } from "@/lib/formatters";
import type { StatusResponse } from "@/lib/api/status";

interface ChartsSectionProps {
  requestsByDay: number[];
  costByDay: number[];
  totalCosts: {
    total_requests: number;
    total_cost_usd: number;
  } | undefined;
  dailyLoading: boolean;
  statusLoading: boolean;
  status: StatusResponse | undefined;
  costsByModel: {
    aggregations: Array<{
      input_tokens: number;
      output_tokens: number;
    }>;
  } | undefined;
}

export function ChartsSection({
  requestsByDay,
  costByDay,
  totalCosts,
  dailyLoading,
  statusLoading,
  status,
  costsByModel,
}: ChartsSectionProps) {
  return (
    <>
      {/* Request Volume Chart */}
      <div className="col-span-8 row-span-2 rounded-xl border border-slate-800/80 bg-slate-900/60 backdrop-blur-sm p-5 overflow-hidden">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
            Request Volume
          </h2>
          <div className="flex items-center gap-4 text-[10px] font-mono text-slate-500">
            <span className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-emerald-500" />
              {formatNumber(totalCosts?.total_requests || 0)} total
            </span>
          </div>
        </div>
        <div className="h-36">
          {dailyLoading ? (
            <div className="h-full bg-slate-800 rounded animate-pulse" />
          ) : (
            <Sparkline data={requestsByDay} color="emerald" showDot />
          )}
        </div>
        {/* Cost mini-chart below */}
        <div className="mt-4 pt-4 border-t border-slate-800/50">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
              Daily Spend
            </span>
            <span className="text-[10px] font-mono text-amber-400">
              {formatCurrency(totalCosts?.total_cost_usd || 0)} total
            </span>
          </div>
          <div className="h-16">
            <Sparkline data={costByDay} color="amber" showDot />
          </div>
        </div>
      </div>

      {/* Provider Health Panel */}
      <div className="col-span-4 row-span-2 rounded-xl border border-slate-800/80 bg-slate-900/60 backdrop-blur-sm p-5 overflow-hidden">
        <h2 className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 mb-4">
          Provider Health
        </h2>
        <div className="space-y-2.5">
          {statusLoading ? (
            <>
              <div className="h-16 bg-slate-800 rounded animate-pulse" />
              <div className="h-16 bg-slate-800 rounded animate-pulse" />
            </>
          ) : status?.providers ? (
            status.providers.map((provider) => (
              <ProviderStatusCard key={provider.name} provider={provider} />
            ))
          ) : (
            <p className="text-sm text-slate-400">No providers configured</p>
          )}
        </div>
        {/* Token summary */}
        <div className="mt-4 pt-4 border-t border-slate-800/50">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 mb-0.5">Input</p>
              <p className="text-lg font-mono font-semibold text-slate-100">
                {formatNumber(costsByModel?.aggregations.reduce((sum, a) => sum + a.input_tokens, 0) || 0)}
              </p>
            </div>
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 mb-0.5">Output</p>
              <p className="text-lg font-mono font-semibold text-slate-100">
                {formatNumber(costsByModel?.aggregations.reduce((sum, a) => sum + a.output_tokens, 0) || 0)}
              </p>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
