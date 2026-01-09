"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  Zap,
  LayoutDashboard,
  MessageSquare,
  History,
  Settings,
  Activity,
  Cpu,
  Server,
  ArrowRight,
  CheckCircle2,
  Clock,
  TrendingUp,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { fetchStatus, fetchCosts, type ProviderStatus } from "@/lib/api";

// Feature card component
function FeatureCard({
  href,
  icon: Icon,
  title,
  description,
  accent,
  stats,
}: {
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  description: string;
  accent: "amber" | "cyan" | "emerald" | "violet";
  stats?: { label: string; value: string };
}) {
  const accentStyles = {
    amber: {
      bg: "bg-amber-50 dark:bg-amber-950/30",
      border: "border-amber-200 dark:border-amber-900/50",
      icon: "text-amber-600 dark:text-amber-400",
      hover: "hover:border-amber-300 dark:hover:border-amber-800",
      glow: "group-hover:shadow-amber-200/50 dark:group-hover:shadow-amber-900/30",
    },
    cyan: {
      bg: "bg-cyan-50 dark:bg-cyan-950/30",
      border: "border-cyan-200 dark:border-cyan-900/50",
      icon: "text-cyan-600 dark:text-cyan-400",
      hover: "hover:border-cyan-300 dark:hover:border-cyan-800",
      glow: "group-hover:shadow-cyan-200/50 dark:group-hover:shadow-cyan-900/30",
    },
    emerald: {
      bg: "bg-emerald-50 dark:bg-emerald-950/30",
      border: "border-emerald-200 dark:border-emerald-900/50",
      icon: "text-emerald-600 dark:text-emerald-400",
      hover: "hover:border-emerald-300 dark:hover:border-emerald-800",
      glow: "group-hover:shadow-emerald-200/50 dark:group-hover:shadow-emerald-900/30",
    },
    violet: {
      bg: "bg-violet-50 dark:bg-violet-950/30",
      border: "border-violet-200 dark:border-violet-900/50",
      icon: "text-violet-600 dark:text-violet-400",
      hover: "hover:border-violet-300 dark:hover:border-violet-800",
      glow: "group-hover:shadow-violet-200/50 dark:group-hover:shadow-violet-900/30",
    },
  };

  const style = accentStyles[accent];

  return (
    <Link
      href={href}
      className={cn(
        "group relative flex flex-col p-6 rounded-xl border-2 transition-all duration-300",
        "bg-white dark:bg-slate-900",
        style.border,
        style.hover,
        "card-hover-lift",
        "group-hover:shadow-xl",
        style.glow,
      )}
    >
      {/* Icon */}
      <div className={cn("inline-flex p-3 rounded-lg mb-4 w-fit", style.bg)}>
        <Icon className={cn("h-6 w-6", style.icon)} />
      </div>

      {/* Content */}
      <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-100 mb-2">
        {title}
      </h3>
      <p className="text-sm text-slate-600 dark:text-slate-400 flex-1">
        {description}
      </p>

      {/* Stats or arrow */}
      <div className="mt-4 pt-4 border-t border-slate-100 dark:border-slate-800 flex items-center justify-between">
        {stats ? (
          <div>
            <p className="text-xs text-slate-500 dark:text-slate-400 uppercase tracking-wider">
              {stats.label}
            </p>
            <p className="text-lg font-mono font-semibold text-slate-900 dark:text-slate-100">
              {stats.value}
            </p>
          </div>
        ) : (
          <span className="text-sm text-slate-500 dark:text-slate-400">
            Get started
          </span>
        )}
        <ArrowRight
          className={cn(
            "h-5 w-5 transition-transform duration-300",
            "text-slate-400 group-hover:text-slate-600 dark:group-hover:text-slate-300",
            "group-hover:translate-x-1",
          )}
        />
      </div>
    </Link>
  );
}

// Provider status badge
function ProviderBadge({ provider }: { provider: ProviderStatus }) {
  const isHealthy = provider.available && provider.health?.state === "healthy";

  return (
    <div
      className={cn(
        "flex items-center gap-2 px-3 py-2 rounded-lg",
        "bg-white dark:bg-slate-800/50",
        "border border-slate-200 dark:border-slate-700",
      )}
    >
      {provider.name === "claude" ? (
        <Cpu className="h-4 w-4 text-orange-500" />
      ) : (
        <Server className="h-4 w-4 text-blue-500" />
      )}
      <span className="text-sm font-medium text-slate-700 dark:text-slate-300 capitalize">
        {provider.name}
      </span>
      <div
        className={cn(
          "h-2 w-2 rounded-full",
          isHealthy ? "bg-emerald-500 animate-status-pulse" : "bg-amber-500",
        )}
      />
    </div>
  );
}

export default function LandingPage() {
  // Fetch live data
  const { data: status } = useQuery({
    queryKey: ["status"],
    queryFn: fetchStatus,
    refetchInterval: 30000,
  });

  const { data: costs } = useQuery({
    queryKey: ["costs", "none", 7],
    queryFn: () => fetchCosts({ group_by: "none", days: 7 }),
    refetchInterval: 60000,
  });

  const formatNumber = (n: number) => {
    if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`;
    if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
    return n.toString();
  };

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950 bg-grid-pattern">
      {/* Hero section */}
      <div className="relative overflow-hidden">
        {/* Gradient overlay */}
        <div className="absolute inset-0 bg-gradient-to-b from-amber-500/5 via-transparent to-transparent pointer-events-none" />

        <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-16 sm:py-24">
          {/* Logo and title */}
          <div className="flex flex-col items-center text-center mb-12">
            <div className="relative mb-6">
              <div className="p-4 rounded-2xl bg-gradient-to-br from-amber-500 to-orange-600 shadow-2xl glow-amber">
                <Zap className="h-10 w-10 text-white" />
              </div>
              {/* Status ring */}
              {status?.status === "healthy" && (
                <div className="absolute -inset-1 rounded-2xl border-2 border-emerald-500/30 animate-pulse" />
              )}
            </div>

            <h1 className="text-4xl sm:text-5xl font-bold tracking-tight text-slate-900 dark:text-slate-100 mb-4">
              Agent <span className="gradient-text-amber">Hub</span>
            </h1>
            <p className="text-lg sm:text-xl text-slate-600 dark:text-slate-400 max-w-2xl">
              Unified command center for agentic AI workloads.
              <br className="hidden sm:block" />
              Monitor, test, and orchestrate Claude and Gemini agents.
            </p>
          </div>

          {/* Status strip */}
          {status && (
            <div className="flex flex-wrap items-center justify-center gap-3 mb-12">
              {/* Overall status */}
              <div
                className={cn(
                  "flex items-center gap-2 px-4 py-2 rounded-full",
                  "bg-white dark:bg-slate-800",
                  "border border-slate-200 dark:border-slate-700",
                  "shadow-sm",
                )}
              >
                <Activity
                  className={cn(
                    "h-4 w-4",
                    status.status === "healthy"
                      ? "text-emerald-500"
                      : "text-amber-500",
                  )}
                />
                <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
                  System <span className="capitalize">{status.status}</span>
                </span>
                <div
                  className={cn(
                    "h-2 w-2 rounded-full",
                    status.status === "healthy"
                      ? "bg-emerald-500"
                      : "bg-amber-500",
                  )}
                />
              </div>

              {/* Provider badges */}
              {status.providers?.map((provider) => (
                <ProviderBadge key={provider.name} provider={provider} />
              ))}

              {/* Uptime */}
              <div className="flex items-center gap-2 px-4 py-2 rounded-full bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 shadow-sm">
                <Clock className="h-4 w-4 text-slate-500" />
                <span className="text-sm font-mono text-slate-600 dark:text-slate-400">
                  {Math.floor(status.uptime_seconds / 3600)}h uptime
                </span>
              </div>
            </div>
          )}

          {/* Feature cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 sm:gap-6">
            <FeatureCard
              href="/dashboard"
              icon={LayoutDashboard}
              title="Dashboard"
              description="Real-time monitoring, cost analytics, and provider health metrics."
              accent="amber"
              stats={
                costs
                  ? {
                      label: "7-day requests",
                      value: formatNumber(costs.total_requests || 0),
                    }
                  : undefined
              }
            />
            <FeatureCard
              href="/chat"
              icon={MessageSquare}
              title="Chat"
              description="Test agents with single or multi-model roundtable conversations."
              accent="cyan"
            />
            <FeatureCard
              href="/sessions"
              icon={History}
              title="Sessions"
              description="Browse conversation history with real-time event streaming."
              accent="emerald"
            />
            <FeatureCard
              href="/settings"
              icon={Settings}
              title="Settings"
              description="Configure API credentials, keys, and user preferences."
              accent="violet"
            />
          </div>
        </div>
      </div>

      {/* Quick stats section */}
      {(status || costs) && (
        <div className="border-t border-slate-200 dark:border-slate-800 bg-white/50 dark:bg-slate-900/50 backdrop-blur-sm">
          <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-6">
              {/* Providers */}
              <div className="text-center">
                <div className="flex items-center justify-center gap-1 mb-1">
                  <CheckCircle2 className="h-4 w-4 text-emerald-500" />
                  <span className="text-2xl font-bold font-mono text-slate-900 dark:text-slate-100">
                    {status?.providers?.filter((p) => p.available).length || 0}
                  </span>
                </div>
                <p className="text-xs text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                  Active Providers
                </p>
              </div>

              {/* Requests */}
              <div className="text-center">
                <div className="flex items-center justify-center gap-1 mb-1">
                  <TrendingUp className="h-4 w-4 text-cyan-500" />
                  <span className="text-2xl font-bold font-mono text-slate-900 dark:text-slate-100">
                    {costs ? formatNumber(costs.total_requests || 0) : "--"}
                  </span>
                </div>
                <p className="text-xs text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                  Requests (7d)
                </p>
              </div>

              {/* Tokens */}
              <div className="text-center">
                <div className="flex items-center justify-center gap-1 mb-1">
                  <Zap className="h-4 w-4 text-amber-500" />
                  <span className="text-2xl font-bold font-mono text-slate-900 dark:text-slate-100">
                    {costs ? formatNumber(costs.total_tokens || 0) : "--"}
                  </span>
                </div>
                <p className="text-xs text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                  Tokens (7d)
                </p>
              </div>

              {/* Cost */}
              <div className="text-center">
                <div className="flex items-center justify-center gap-1 mb-1">
                  <span className="text-2xl font-bold font-mono text-slate-900 dark:text-slate-100">
                    ${costs?.total_cost_usd?.toFixed(2) || "0.00"}
                  </span>
                </div>
                <p className="text-xs text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                  Cost (7d)
                </p>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Footer */}
      <footer className="border-t border-slate-200 dark:border-slate-800">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <div className="flex flex-col sm:flex-row items-center justify-between gap-4">
            <div className="flex items-center gap-2">
              <div className="p-1.5 rounded-md bg-gradient-to-br from-amber-500 to-orange-600">
                <Zap className="h-3.5 w-3.5 text-white" />
              </div>
              <span className="text-sm font-medium text-slate-600 dark:text-slate-400">
                Agent Hub
              </span>
            </div>
            <p className="text-xs text-slate-500 dark:text-slate-500">
              Unified agentic AI service for Claude & Gemini workloads
            </p>
          </div>
        </div>
      </footer>
    </div>
  );
}
