"use client";

import { use, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import {
  ArrowLeft,
  Clock,
  Cpu,
  Server,
  AlertCircle,
  Gauge,
  Activity,
  LayoutList,
  Hash,
  Layers,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  fetchSession,
  fetchSessionEvents,
  type ContextUsage,
} from "@/lib/api";
import { EventTimeline } from "@/components/timeline";

function formatDate(dateString: string): string {
  const date = new Date(dateString);
  return date.toLocaleString();
}

function formatTokens(tokens: number): string {
  if (tokens >= 1000000) return `${(tokens / 1000000).toFixed(1)}M`;
  if (tokens >= 1000) return `${(tokens / 1000).toFixed(1)}K`;
  return tokens.toString();
}

function getProviderIcon(provider: string) {
  if (provider === "claude") {
    return <Cpu className="h-5 w-5 text-orange-500" />;
  }
  return <Server className="h-5 w-5 text-blue-500" />;
}

function ContextUsageBar({ usage }: { usage: ContextUsage }) {
  const percent = Math.min(100, usage.percent_used);
  const isWarning = percent > 70;
  const isDanger = percent > 90;

  return (
    <div
      className={cn(
        "p-4 rounded-lg",
        "bg-slate-900/60 border border-slate-800/60"
      )}
    >
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Gauge className="h-4 w-4 text-slate-500" />
          <span className="text-sm font-medium text-slate-300">
            Context Usage
          </span>
        </div>
        <span className="text-sm font-mono text-slate-400">
          {formatTokens(usage.used_tokens)} / {formatTokens(usage.limit_tokens)}
        </span>
      </div>
      <div className="h-2 bg-slate-800/80 rounded-full overflow-hidden">
        <div
          className={cn(
            "h-full rounded-full transition-all duration-500",
            isDanger
              ? "bg-gradient-to-r from-red-600 to-red-500"
              : isWarning
                ? "bg-gradient-to-r from-amber-600 to-amber-500"
                : "bg-gradient-to-r from-emerald-600 to-emerald-500"
          )}
          style={{ width: `${percent}%` }}
        />
      </div>
      <div className="mt-2 flex items-center justify-between text-xs text-slate-500">
        <span>{percent.toFixed(1)}% used</span>
        <span>{formatTokens(usage.remaining_tokens)} remaining</span>
      </div>
      {usage.warning && (
        <div className="mt-2 flex items-center gap-1.5 text-xs text-amber-400">
          <AlertCircle className="h-3.5 w-3.5" />
          <span>{usage.warning}</span>
        </div>
      )}
    </div>
  );
}

interface StatCardProps {
  icon: typeof Activity;
  label: string;
  value: string | number;
  subValue?: string;
}

function StatCard({ icon: Icon, label, value, subValue }: StatCardProps) {
  return (
    <div
      className={cn(
        "p-3 rounded-lg",
        "bg-slate-900/60 border border-slate-800/60"
      )}
    >
      <div className="flex items-center gap-2 mb-1">
        <Icon className="h-3.5 w-3.5 text-slate-500" />
        <span className="text-xs text-slate-500">{label}</span>
      </div>
      <p className="text-sm font-medium text-slate-300 truncate">{value}</p>
      {subValue && (
        <p className="text-xs text-slate-600 mt-0.5 truncate">{subValue}</p>
      )}
    </div>
  );
}

export default function SessionDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const [activeTab, setActiveTab] = useState<"timeline" | "info">("timeline");

  const {
    data: session,
    isLoading: sessionLoading,
    error: sessionError,
  } = useQuery({
    queryKey: ["session", id],
    queryFn: () => fetchSession(id),
  });

  const {
    data: eventsData,
    isLoading: eventsLoading,
    error: eventsError,
  } = useQuery({
    queryKey: ["session-events", id],
    queryFn: () => fetchSessionEvents(id, { page_size: 500 }),
  });

  const isLoading = sessionLoading || eventsLoading;
  const error = sessionError || eventsError;

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      {/* Header */}
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

              {session && (
                <div className="flex items-center gap-3">
                  <div
                    className={cn(
                      "p-2 rounded-lg",
                      "bg-slate-900/80 border border-slate-800/60"
                    )}
                  >
                    {getProviderIcon(session.provider)}
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <h1 className="text-base font-semibold font-mono text-slate-200">
                        {id.slice(0, 8)}
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
                    <p className="text-xs text-slate-500">{session.model}</p>
                  </div>
                </div>
              )}
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
                  onClick={() => setActiveTab("timeline")}
                  className={cn(
                    "flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all",
                    activeTab === "timeline"
                      ? "bg-slate-800 text-slate-200 shadow-sm"
                      : "text-slate-500 hover:text-slate-400"
                  )}
                >
                  <Activity className="h-3.5 w-3.5" />
                  Timeline
                </button>
                <button
                  onClick={() => setActiveTab("info")}
                  className={cn(
                    "flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all",
                    activeTab === "info"
                      ? "bg-slate-800 text-slate-200 shadow-sm"
                      : "text-slate-500 hover:text-slate-400"
                  )}
                >
                  <LayoutList className="h-3.5 w-3.5" />
                  Info
                </button>
              </div>

              {/* Quick stats */}
              {eventsData && (
                <div className="hidden md:flex items-center gap-3 text-xs text-slate-500">
                  <div className="flex items-center gap-1">
                    <Hash className="h-3.5 w-3.5" />
                    <span className="font-mono">{eventsData.total} events</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <Layers className="h-3.5 w-3.5" />
                    <span className="font-mono">{eventsData.max_turn} turns</span>
                  </div>
                </div>
              )}

              {session && (
                <div className="flex items-center gap-1 text-xs text-slate-500">
                  <Clock className="h-3.5 w-3.5" />
                  <span>{formatDate(session.created_at)}</span>
                </div>
              )}
            </div>
          </div>
        </div>
      </header>

      {/* Main content */}
      <main className="h-[calc(100vh-3.5rem)]">
        {/* Error State */}
        {error && (
          <div className="p-6">
            <div
              className={cn(
                "flex items-center gap-2 p-4 rounded-lg",
                "bg-red-950/40 border border-red-800/50",
                "text-red-400"
              )}
            >
              <AlertCircle className="h-5 w-5" />
              <p className="text-sm">Failed to load session</p>
            </div>
          </div>
        )}

        {/* Loading State */}
        {isLoading && (
          <div className="flex items-center justify-center h-full">
            <div className="flex flex-col items-center gap-3 text-slate-500">
              <div className="w-8 h-8 border-2 border-slate-700 border-t-slate-400 rounded-full animate-spin" />
              <p className="text-sm">Loading session...</p>
            </div>
          </div>
        )}

        {/* Content */}
        {!isLoading && !error && session && (
          <>
            {activeTab === "timeline" && eventsData && (
              <EventTimeline
                events={eventsData.events}
                className="h-full"
              />
            )}

            {activeTab === "info" && (
              <div className="p-6 max-w-4xl space-y-6">
                {/* Context Usage */}
                {session.context_usage && (
                  <ContextUsageBar usage={session.context_usage} />
                )}

                {/* Session Info Grid */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                  <StatCard
                    icon={Layers}
                    label="Project"
                    value={session.project_id}
                  />
                  <StatCard
                    icon={Cpu}
                    label="Provider"
                    value={session.provider}
                    subValue={session.model}
                  />
                  <StatCard
                    icon={Activity}
                    label="Type"
                    value={session.session_type}
                  />
                  <StatCard
                    icon={Clock}
                    label="Updated"
                    value={formatDate(session.updated_at)}
                  />
                </div>

                {/* Token breakdown */}
                {session.agent_token_breakdown &&
                  session.agent_token_breakdown.length > 0 && (
                    <div
                      className={cn(
                        "p-4 rounded-lg",
                        "bg-slate-900/60 border border-slate-800/60"
                      )}
                    >
                      <h3 className="text-sm font-medium text-slate-300 mb-3">
                        Token Breakdown by Agent
                      </h3>
                      <div className="space-y-2">
                        {session.agent_token_breakdown.map((agent) => (
                          <div
                            key={agent.agent_id}
                            className="flex items-center justify-between py-2 border-b border-slate-800/40 last:border-0"
                          >
                            <div>
                              <p className="text-sm text-slate-300">
                                {agent.agent_name || agent.agent_id}
                              </p>
                              <p className="text-xs text-slate-500">
                                {agent.message_count} messages
                              </p>
                            </div>
                            <div className="text-right">
                              <p className="text-sm font-mono text-slate-300">
                                {formatTokens(agent.total_tokens)}
                              </p>
                              <p className="text-xs text-slate-500 font-mono">
                                {formatTokens(agent.input_tokens)} in /{" "}
                                {formatTokens(agent.output_tokens)} out
                              </p>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                {/* Totals */}
                {(session.total_input_tokens || session.total_output_tokens) && (
                  <div className="grid grid-cols-2 gap-3">
                    <div
                      className={cn(
                        "p-4 rounded-lg text-center",
                        "bg-sky-950/30 border border-sky-800/40"
                      )}
                    >
                      <p className="text-2xl font-mono font-semibold text-sky-400">
                        {formatTokens(session.total_input_tokens || 0)}
                      </p>
                      <p className="text-xs text-sky-500 mt-1">Input Tokens</p>
                    </div>
                    <div
                      className={cn(
                        "p-4 rounded-lg text-center",
                        "bg-violet-950/30 border border-violet-800/40"
                      )}
                    >
                      <p className="text-2xl font-mono font-semibold text-violet-400">
                        {formatTokens(session.total_output_tokens || 0)}
                      </p>
                      <p className="text-xs text-violet-500 mt-1">Output Tokens</p>
                    </div>
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}
