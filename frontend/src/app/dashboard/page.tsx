"use client";

import { useState } from "react";
import { AlertTriangle } from "lucide-react";
import { TabNavigation, type TabId } from "@/components/dashboard/TabNavigation";
import { SessionsTabContent } from "@/components/dashboard/tabs/SessionsTabContent";
import { AnalyticsTabContent } from "@/components/dashboard/tabs/AnalyticsTabContent";
import { HealthTabContent } from "@/components/dashboard/tabs/HealthTabContent";
import { useDashboardData } from "./hooks/useDashboardData";
import { DashboardHeader } from "./components/DashboardHeader";
import { KPISection } from "./components/KPISection";
import { ChartsSection } from "./components/ChartsSection";

export default function DashboardPage() {
  const [activeTab, setActiveTab] = useState<TabId>("sessions");
  const [daysRange, setDaysRange] = useState(7);
  const [showRangeDropdown, setShowRangeDropdown] = useState(false);

  const {
    activeSessionCount,
    status,
    statusError,
    totalCosts,
    costsByProject,
    projectLoading,
    costsByModel,
    modelLoading,
    sessionsData,
    sessionsLoading,
    dashboardStats,
    requestsByDay,
    costByDay,
    dailyLoading,
    statusLoading,
  } = useDashboardData({ daysRange });

  const handleRangeChange = (days: number) => {
    setDaysRange(days);
    setShowRangeDropdown(false);
  };

  return (
    <div className="min-h-screen bg-slate-950">
      {/* Subtle background pattern */}
      <div className="fixed inset-0 bg-grid-pattern pointer-events-none opacity-30" />

      <DashboardHeader
        status={status}
        daysRange={daysRange}
        showRangeDropdown={showRangeDropdown}
        onToggleDropdown={() => setShowRangeDropdown(!showRangeDropdown)}
        onRangeChange={handleRangeChange}
      />

      <main className="relative px-6 lg:px-8 py-5">
        {/* Error Banner */}
        {statusError && (
          <div className="mb-4 p-3 rounded-lg bg-red-900/20 border border-red-800/50 flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-red-500" />
            <p className="text-sm text-red-400">
              Unable to connect to backend
            </p>
          </div>
        )}

        {/* BENTO GRID LAYOUT */}
        <div className="grid grid-cols-12 gap-4 auto-rows-min">
          <KPISection
            dashboardStats={dashboardStats}
            activeSessionCount={activeSessionCount}
            totalCosts={totalCosts}
          />

          <ChartsSection
            requestsByDay={requestsByDay}
            costByDay={costByDay}
            totalCosts={totalCosts}
            dailyLoading={dailyLoading}
            statusLoading={statusLoading}
            status={status}
            costsByModel={costsByModel}
          />

          {/* ROW 3: Tabbed Section (full width) */}
          <div className="col-span-12 rounded-xl border border-slate-800/80 bg-slate-900/60 backdrop-blur-sm p-5 overflow-hidden">
            <div className="flex items-center justify-between mb-4">
              <TabNavigation activeTab={activeTab} onTabChange={setActiveTab} />
              {activeTab === "sessions" && (
                <a
                  href="/sessions"
                  className="text-[10px] font-medium text-slate-500 hover:text-slate-300 transition-colors"
                >
                  View all
                </a>
              )}
            </div>

            {/* Tab Content */}
            <div className="min-h-[200px]">
              {activeTab === "sessions" && (
                <SessionsTabContent
                  sessions={sessionsData?.sessions || []}
                  isLoading={sessionsLoading}
                />
              )}
              {activeTab === "analytics" && (
                <AnalyticsTabContent
                  costsByProject={costsByProject}
                  costsByModel={costsByModel}
                  isLoading={projectLoading || modelLoading}
                />
              )}
              {activeTab === "health" && (
                <HealthTabContent
                  stats={dashboardStats}
                  status={status}
                />
              )}
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
