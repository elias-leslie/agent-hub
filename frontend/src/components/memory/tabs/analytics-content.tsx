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
import {
  type MemoryAnalytics,
  type MetricsDashboard,
  type TopMemory,
  type TierChangesSummary,
} from "@/lib/memory-api";
import {
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
  analytics: MemoryAnalytics;
  metrics: MetricsDashboard | undefined;
  topMemories: TopMemory[];
  tierChanges: TierChangesSummary | undefined;
  days: number;
  onDaysChange: (days: number) => void;
  topMemoriesSortBy: string;
  onTopMemoriesSortChange: (field: string) => void;
  onTierClick: (tier: string) => void;
  onMemoryClick: (uuid: string) => void;
}

function KpiCards({ analytics }: { analytics: MemoryAnalytics }) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-6 gap-3">
      <MetricCard
        label="Total Episodes"
        value={analytics.total_episodes.toLocaleString()}
        icon={Database}
        color="emerald"
      />
      <MetricCard
        label="Success Rate"
        value={`${(analytics.success_rate * 100).toFixed(1)}%`}
        icon={CheckCircle2}
        color="green"
      />
      <MetricCard
        label="Citation Rate"
        value={`${(analytics.citation_rate * 100).toFixed(1)}%`}
        icon={Quote}
        color="purple"
      />
      <MetricCard
        label="Avg Utility"
        value={analytics.avg_utility_score.toFixed(2)}
        icon={TrendingUp}
        color="sky"
      />
      <MetricCard
        label="Avg Lifecycle"
        value={analytics.avg_lifecycle_score.toFixed(2)}
        icon={Heart}
        color="rose"
      />
      <MetricCard
        label="Total Loaded"
        value={analytics.total_loaded.toLocaleString()}
        icon={Download}
        color="amber"
      />
    </div>
  );
}

interface DistributionRowProps {
  analytics: MemoryAnalytics;
  metrics: MetricsDashboard | undefined;
  onTierClick: (tier: string) => void;
}

function DistributionRow({ analytics, metrics, onTierClick }: DistributionRowProps) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      <div className="bg-slate-900/60 border border-slate-800/80 rounded-lg p-5">
        <SectionHeader title="Tier Distribution" icon={Layers} />
        <TierChart data={analytics.tier_distribution} onTierClick={onTierClick} />
      </div>
      <div className="bg-slate-900/60 border border-slate-800/80 rounded-lg p-5">
        <SectionHeader title="Scope Distribution" icon={Database} />
        <ScopeChart data={analytics.scope_distribution} />
      </div>
      <div className="bg-slate-900/60 border border-slate-800/80 rounded-lg p-5">
        <SectionHeader title="Feedback Loops" icon={Activity} />
        <FeedbackLoopsHealth analytics={analytics} metrics={metrics} />
      </div>
    </div>
  );
}

interface DetailRowProps {
  analytics: MemoryAnalytics;
  topMemories: TopMemory[];
  tierChanges: TierChangesSummary | undefined;
  topMemoriesSortBy: string;
  onTopMemoriesSortChange: (field: string) => void;
  onMemoryClick: (uuid: string) => void;
}

function DetailRow({
  analytics,
  topMemories,
  tierChanges,
  topMemoriesSortBy,
  onTopMemoriesSortChange,
  onMemoryClick,
}: DetailRowProps) {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
      <div className="bg-slate-900/60 border border-slate-800/80 rounded-lg p-5">
        <SectionHeader title="Usage Stats" icon={BarChart3} />
        <UsageStats data={analytics} />
      </div>
      <div className="bg-slate-900/60 border border-slate-800/80 rounded-lg p-5">
        <SectionHeader title="Top Performing Memories" icon={Trophy} />
        <TopMemoriesTable
          data={topMemories}
          sortBy={topMemoriesSortBy}
          onSortChange={onTopMemoriesSortChange}
          onRowClick={onMemoryClick}
        />
      </div>
      <div className="bg-slate-900/60 border border-slate-800/80 rounded-lg p-5">
        <SectionHeader title="Tier Changes" icon={ArrowUpDown} />
        <TierChangesSection data={tierChanges} />
      </div>
    </div>
  );
}

export function AnalyticsContent({
  analytics,
  metrics,
  topMemories,
  tierChanges,
  days,
  onDaysChange,
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
        <TimeRangeSelector value={days} onChange={onDaysChange} />
      </div>
      <KpiCards analytics={analytics} />
      <DistributionRow analytics={analytics} metrics={metrics} onTierClick={onTierClick} />
      <div className="bg-slate-900/60 border border-slate-800/80 rounded-lg p-5">
        <SectionHeader title="Injection Metrics Over Time" icon={TrendingUp} />
        <InjectionMetricsChart data={metrics} />
      </div>
      <DetailRow
        analytics={analytics}
        topMemories={topMemories}
        tierChanges={tierChanges}
        topMemoriesSortBy={topMemoriesSortBy}
        onTopMemoriesSortChange={onTopMemoriesSortChange}
        onMemoryClick={onMemoryClick}
      />
    </div>
  );
}
