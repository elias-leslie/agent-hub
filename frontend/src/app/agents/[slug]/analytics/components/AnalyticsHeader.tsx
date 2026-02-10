import { useRouter } from "next/navigation";
import { Bot, ArrowLeft, RefreshCw } from "lucide-react";

interface AnalyticsHeaderProps {
  agentName: string;
  slug: string;
  timeRange: string;
  onTimeRangeChange: (value: string) => void;
}

export function AnalyticsHeader({
  agentName,
  slug,
  timeRange,
  onTimeRangeChange,
}: AnalyticsHeaderProps) {
  const router = useRouter();

  return (
    <header className="sticky top-0 z-30 border-b border-slate-200 dark:border-slate-800 bg-white/95 dark:bg-slate-900/95 backdrop-blur-sm">
      <div className="px-6 lg:px-8">
        <div className="flex items-center justify-between h-14">
          <div className="flex items-center gap-4">
            <button
              onClick={() => router.push(`/agents/${slug}`)}
              className="p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
            >
              <ArrowLeft className="h-5 w-5 text-slate-600 dark:text-slate-400" />
            </button>
            <div className="flex items-center gap-2">
              <Bot className="h-5 w-5 text-slate-600 dark:text-slate-400" />
              <h1 className="text-lg font-bold text-slate-900 dark:text-slate-100 tracking-tight">
                {agentName}
              </h1>
              <span className="text-xs font-medium text-slate-400 bg-slate-100 dark:bg-slate-800 px-2 py-0.5 rounded">
                Analytics
              </span>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <select
              value={timeRange}
              onChange={(e) => onTimeRangeChange(e.target.value)}
              className="px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-xs font-medium focus:outline-none focus:ring-2 focus:ring-blue-500/40"
            >
              <option value="24h">Last 24 hours</option>
              <option value="7d">Last 7 days</option>
              <option value="30d">Last 30 days</option>
            </select>
            <button className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors">
              <RefreshCw className="h-3.5 w-3.5" />
              Refresh
            </button>
          </div>
        </div>
      </div>
    </header>
  );
}
