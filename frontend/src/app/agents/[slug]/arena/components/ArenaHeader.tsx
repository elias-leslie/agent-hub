import { useRouter } from "next/navigation";
import { ArrowLeft, FlaskConical, RefreshCw } from "lucide-react";

import { cn } from "@/lib/utils";

type ArenaWindow = 7 | 30 | 90;
export type ArenaView = "overview" | "suites" | "runtime" | "experiments";

interface ArenaHeaderProps {
  agentName: string;
  slug: string;
  backHref?: string;
  windowDays: ArenaWindow;
  activeView: ArenaView;
  onWindowDaysChange: (value: ArenaWindow) => void;
  onViewChange: (value: ArenaView) => void;
  onRefresh: () => void;
  isRefreshing: boolean;
}

const VIEW_OPTIONS: Array<{ id: ArenaView; label: string }> = [
  { id: "overview", label: "Overview" },
  { id: "suites", label: "Suites" },
  { id: "runtime", label: "Runtime" },
  { id: "experiments", label: "Experiments" },
];

export function ArenaHeader({
  agentName,
  slug,
  backHref,
  windowDays,
  activeView,
  onWindowDaysChange,
  onViewChange,
  onRefresh,
  isRefreshing,
}: ArenaHeaderProps) {
  const router = useRouter();

  return (
    <header className="sticky top-0 z-30 border-b border-slate-200 bg-white/95 backdrop-blur-sm dark:border-slate-800 dark:bg-slate-900/95">
      <div className="px-6 lg:px-8">
        <div className="flex flex-col gap-3 py-3">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex items-center gap-4">
              <button
                onClick={() => router.push(backHref || `/agents/${slug}`)}
                className="rounded-lg p-1.5 transition-colors hover:bg-slate-100 dark:hover:bg-slate-800"
                aria-label="Back"
              >
                <ArrowLeft className="h-5 w-5 text-slate-600 dark:text-slate-400" />
              </button>
              <div className="flex items-center gap-2">
                <FlaskConical className="h-5 w-5 text-cyan-600 dark:text-cyan-400" />
                <h1 className="text-lg font-bold tracking-tight text-slate-900 dark:text-slate-100">
                  {agentName}
                </h1>
                <span className="rounded bg-cyan-50 px-2 py-0.5 text-xs font-semibold text-cyan-700 ring-1 ring-cyan-200 dark:bg-cyan-950/40 dark:text-cyan-200 dark:ring-cyan-900">
                  Arena
                </span>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2 lg:justify-end">
              <select
                value={windowDays}
                onChange={(event) => onWindowDaysChange(Number(event.target.value) as ArenaWindow)}
                className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium focus:outline-none focus:ring-2 focus:ring-cyan-500/40 dark:border-slate-700 dark:bg-slate-800"
              >
                <option value="7">Last 7 days</option>
                <option value="30">Last 30 days</option>
                <option value="90">Last 90 days</option>
              </select>
              <button
                onClick={onRefresh}
                disabled={isRefreshing}
                className="inline-flex items-center gap-1.5 rounded-lg bg-slate-100 px-3 py-1.5 text-xs font-medium transition-colors hover:bg-slate-200 disabled:opacity-50 dark:bg-slate-800 dark:hover:bg-slate-700"
              >
                <RefreshCw className={cn("h-3.5 w-3.5", isRefreshing && "animate-spin")} />
                Refresh
              </button>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {VIEW_OPTIONS.map((view) => (
              <button
                key={view.id}
                type="button"
                onClick={() => onViewChange(view.id)}
                className={cn(
                  "rounded-full px-3 py-1.5 text-xs font-semibold transition-colors",
                  activeView === view.id
                    ? "bg-slate-900 text-white dark:bg-cyan-600"
                    : "bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700",
                )}
                aria-pressed={activeView === view.id}
              >
                {view.label}
              </button>
            ))}
          </div>
        </div>
      </div>
    </header>
  );
}
