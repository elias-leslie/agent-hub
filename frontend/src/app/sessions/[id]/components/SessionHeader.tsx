import Link from "next/link";
import {
  ArrowLeft,
  Clock,
  Activity,
  LayoutList,
  Hash,
  Layers,
  BookOpen,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { Session } from "@/lib/api";
import type { SessionMemoryObservability } from "@/lib/session-memory-observability";
import { formatDate, getProviderIcon } from "./utils";

interface SessionHeaderProps {
  session: Session;
  sessionId: string;
  activeTab: "timeline" | "info";
  onTabChange: (tab: "timeline" | "info") => void;
  eventsTotal?: number;
  maxTurn?: number;
  memorySummary?: SessionMemoryObservability | null;
}

export function SessionHeader({
  session,
  sessionId,
  activeTab,
  onTabChange,
  eventsTotal,
  maxTurn,
  memorySummary,
}: SessionHeaderProps) {
  const requestedModel = session.requested_model || session.model;
  const effectiveModel = session.effective_model || session.model;
  const effectiveProvider = session.effective_provider || session.provider;
  const showsFallback = session.fallback_used && requestedModel !== effectiveModel;
  const liveActivity = session.live_activity;
  const liveLabel = liveActivity
    ? `${liveActivity.health} · ${liveActivity.phase}`
    : null;

  return (
    <header
      className={cn(
        "sticky top-0 z-30",
        "border-b border-slate-800/60",
        "bg-slate-950/95 backdrop-blur-sm"
      )}
    >
      <div className="px-6 lg:px-8">
        <div className="flex items-center justify-between h-14">
          {/* Left: Back + Session info */}
          <div className="flex items-center gap-4">
            <Link
              href="/sessions"
              className={cn(
                "p-1.5 -ml-1.5 rounded-lg",
                "text-slate-500 hover:text-slate-300",
                "hover:bg-slate-800/60 transition-colors"
              )}
            >
              <ArrowLeft className="h-4 w-4" />
            </Link>

            <div className="flex items-center gap-3">
              <div
                className={cn(
                  "p-2 rounded-lg",
                  "bg-slate-900/80 border border-slate-800/60"
                )}
              >
                {getProviderIcon(effectiveProvider)}
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <h1 className="text-base font-semibold font-mono text-slate-200">
                    {sessionId.slice(0, 8)}
                  </h1>
                  <span
                    className={cn(
                      "px-2 py-0.5 rounded text-xs font-medium",
                      session.status === "active"
                        ? "bg-emerald-950/60 text-emerald-400 border border-emerald-800/50"
                        : session.status === "failed"
                          ? "bg-red-950/60 text-red-400 border border-red-800/50"
                          : "bg-slate-800/60 text-slate-400 border border-slate-700/50"
                    )}
                  >
                    {session.status}
                  </span>
                </div>
                <div className="text-xs text-slate-500">
                  <p>{effectiveModel}</p>
                  {showsFallback && (
                    <p className="text-amber-500/80">
                      requested {requestedModel}
                    </p>
                  )}
                  {liveLabel && (
                    <p className="text-sky-400/80">{liveLabel}</p>
                  )}
                </div>
              </div>
            </div>
          </div>

          {/* Right: Tabs + Stats */}
          <div className="flex items-center gap-4">
            {/* Tab switcher */}
            <div
              className={cn(
                "flex items-center gap-1 p-1 rounded-lg",
                "bg-slate-900/60 border border-slate-800/60"
              )}
            >
              <button
                onClick={() => onTabChange("timeline")}
                className={cn(
                  "flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all",
                  activeTab === "timeline"
                    ? "bg-amber-950/50 text-amber-200 shadow-sm ring-1 ring-amber-800/50"
                    : "text-slate-500 hover:text-slate-400"
                )}
              >
                <Activity className="h-3.5 w-3.5" />
                Timeline
              </button>
              <button
                onClick={() => onTabChange("info")}
                className={cn(
                  "flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all",
                  activeTab === "info"
                    ? "bg-amber-950/50 text-amber-200 shadow-sm ring-1 ring-amber-800/50"
                    : "text-slate-500 hover:text-slate-400"
                )}
              >
                <LayoutList className="h-3.5 w-3.5" />
                Info
              </button>
            </div>

            {/* Quick stats */}
            {eventsTotal !== undefined && maxTurn !== undefined && (
              <div className="hidden md:flex items-center gap-3 text-xs text-slate-500">
                <div className="flex items-center gap-1">
                  <Hash className="h-3.5 w-3.5" />
                  <span className="font-mono">{eventsTotal} events</span>
                </div>
                <div className="flex items-center gap-1">
                  <Layers className="h-3.5 w-3.5" />
                  <span className="font-mono">{maxTurn} turns</span>
                </div>
                {memorySummary && (
                  <div className="flex items-center gap-1">
                    <BookOpen className="h-3.5 w-3.5" />
                    <span className="font-mono">
                      refs {memorySummary.selectedCount}/{memorySummary.indexCount} cited{" "}
                      {memorySummary.selectedCitedCount}/{memorySummary.selectedCount}
                    </span>
                  </div>
                )}
              </div>
            )}

            <div className="flex items-center gap-1 text-xs text-slate-500">
              <Clock className="h-3.5 w-3.5" />
              <span>{formatDate(session.created_at)}</span>
            </div>
          </div>
        </div>
      </div>
    </header>
  );
}
