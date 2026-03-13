import {
  BarChart3,
  Database,
  Quote,
  TrendingUp,
  Download,
  Layers,
  CheckCircle2,
  Activity,
  Trophy,
  Heart,
  ArrowUpDown,
} from "lucide-react";
import { type MemoryAnalyticsDashboard } from "@/lib/memory-api";
import {
  type AnalyticsLookback,
  MetricCard,
  SectionHeader,
  TimeRangeSelector,
} from "./analytics-components";
import {
  TierChart,
  ScopeChart,
  InjectionMetricsChart,
  FeedbackLoopsHealth,
  TopMemoriesTable,
  UsageStats,
} from "./analytics-charts";
import { TierChangesSection } from "./tier-changes-section";

export interface AnalyticsContentProps {
  analytics: MemoryAnalyticsDashboard;
  lookback: AnalyticsLookback;
  onLookbackChange: (lookback: AnalyticsLookback) => void;
  topMemoriesSortBy: string;
  onTopMemoriesSortChange: (field: string) => void;
  onTierClick: (tier: string) => void;
  onMemoryClick: (uuid: string) => void;
}

function StateKpiCards({ analytics }: { analytics: MemoryAnalyticsDashboard["state"] }) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-6 gap-3">
      <MetricCard label="Total Episodes" value={analytics.total_episodes.toLocaleString()} icon={Database} color="emerald" />
      <MetricCard label="Avg Utility" value={analytics.avg_utility_score.toFixed(2)} icon={TrendingUp} color="sky" />
      <MetricCard label="Avg Lifecycle" value={analytics.avg_lifecycle_score.toFixed(2)} icon={Heart} color="rose" />
      <MetricCard label="Total Loaded" value={analytics.usage_totals.loaded.toLocaleString()} icon={Download} color="amber" />
      <MetricCard label="Total Cited" value={analytics.usage_totals.cited.toLocaleString()} icon={Quote} color="purple" />
      <MetricCard label="Helpful" value={analytics.usage_totals.helpful.toLocaleString()} icon={CheckCircle2} color="green" />
    </div>
  );
}

function ActivityKpiCards({ analytics }: { analytics: MemoryAnalyticsDashboard["activity"] }) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-6 gap-3">
      <MetricCard label="Injections" value={analytics.injection_metrics.total_injections.toLocaleString()} icon={Download} color="amber" />
      <MetricCard label="Recent Cited" value={analytics.usage_totals.cited.toLocaleString()} icon={Quote} color="purple" />
      <MetricCard label="Helpful Signals" value={analytics.usage_totals.helpful.toLocaleString()} icon={Heart} color="rose" />
      <MetricCard label="Outcome Coverage" value={`${(analytics.injection_metrics.outcomes.coverage_rate * 100).toFixed(1)}%`} icon={Activity} color="emerald" />
      <MetricCard label="Success Rate" value={`${(analytics.injection_metrics.outcomes.success_rate * 100).toFixed(1)}%`} icon={CheckCircle2} color="green" />
      <MetricCard label="Citation Rate" value={`${(analytics.injection_metrics.overall_citation_rate * 100).toFixed(1)}%`} icon={TrendingUp} color="sky" />
      <MetricCard label="Type Changes" value={analytics.tier_changes.total.toLocaleString()} icon={ArrowUpDown} color="amber" />
    </div>
  );
}

interface StateDistributionRowProps {
  analytics: MemoryAnalyticsDashboard["state"];
  onTierClick: (tier: string) => void;
}

function StateDistributionRow({ analytics, onTierClick }: StateDistributionRowProps) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      <div className="bg-slate-900/60 border border-slate-800/80 rounded-lg p-5">
        <SectionHeader title="Type Distribution" icon={Layers} />
        <TierChart data={analytics.tier_distribution} onTierClick={onTierClick} />
      </div>
      <div className="bg-slate-900/60 border border-slate-800/80 rounded-lg p-5">
        <SectionHeader title="Scope Distribution" icon={Database} />
        <ScopeChart data={analytics.scope_distribution} />
      </div>
      <div className="bg-slate-900/60 border border-slate-800/80 rounded-lg p-5">
        <SectionHeader title="Current Usage" icon={Activity} />
        <UsageStats data={analytics.usage_totals} />
      </div>
    </div>
  );
}

interface DetailRowProps {
  analytics: MemoryAnalyticsDashboard;
  topMemoriesSortBy: string;
  onTopMemoriesSortChange: (field: string) => void;
  onMemoryClick: (uuid: string) => void;
}

function DetailRow({
  analytics,
  topMemoriesSortBy,
  onTopMemoriesSortChange,
  onMemoryClick,
}: DetailRowProps) {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
      <div className="bg-slate-900/60 border border-slate-800/80 rounded-lg p-5">
        <SectionHeader title="Recent Feedback Loops" icon={BarChart3} />
        <FeedbackLoopsHealth activity={analytics.activity} />
      </div>
      <div className="bg-slate-900/60 border border-slate-800/80 rounded-lg p-5">
        <SectionHeader title="Top Performing Memories" icon={Trophy} />
        <TopMemoriesTable
          data={analytics.state.top_memories}
          sortBy={topMemoriesSortBy}
          onSortChange={onTopMemoriesSortChange}
          onRowClick={onMemoryClick}
        />
      </div>
      <div className="bg-slate-900/60 border border-slate-800/80 rounded-lg p-5">
        <SectionHeader title="Type Changes" icon={ArrowUpDown} />
        <TierChangesSection data={analytics.activity.tier_changes} />
      </div>
    </div>
  );
}

export function AnalyticsContent({
  analytics,
  lookback,
  onLookbackChange,
  topMemoriesSortBy,
  onTopMemoriesSortChange,
  onTierClick,
  onMemoryClick,
}: AnalyticsContentProps) {
  return (
    <div className="p-4 space-y-4 overflow-auto">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wide">
          Memory Analytics
        </h2>
        <TimeRangeSelector value={lookback} onChange={onLookbackChange} />
      </div>
      <div className="space-y-3">
        <SectionHeader title="Current State" icon={Database} />
        <StateKpiCards analytics={analytics.state} />
      </div>
      <StateDistributionRow analytics={analytics.state} onTierClick={onTierClick} />
      <div className="space-y-3">
        <SectionHeader title={`Recent Activity (${analytics.activity.lookback})`} icon={TrendingUp} />
        <ActivityKpiCards analytics={analytics.activity} />
      </div>
      <div className="bg-slate-900/60 border border-slate-800/80 rounded-lg p-5">
        <SectionHeader title="Injection Metrics Over Time" icon={TrendingUp} />
        <InjectionMetricsChart data={analytics.activity.injection_metrics} />
      </div>
      <DetailRow
        analytics={analytics}
        topMemoriesSortBy={topMemoriesSortBy}
        onTopMemoriesSortChange={onTopMemoriesSortChange}
        onMemoryClick={onMemoryClick}
      />
    </div>
  );
}
