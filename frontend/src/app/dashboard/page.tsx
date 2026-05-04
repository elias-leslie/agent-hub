'use client'

import { AlertTriangle } from 'lucide-react'
import { useState } from 'react'
import { type TabId, TabNavigation } from '@/components/dashboard/TabNavigation'
import { AnalyticsTabContent } from '@/components/dashboard/tabs/AnalyticsTabContent'
import { HealthTabContent } from '@/components/dashboard/tabs/HealthTabContent'
import { SessionsTabContent } from '@/components/dashboard/tabs/SessionsTabContent'
import { ChartsSection } from './components/ChartsSection'
import { DashboardHeader } from './components/DashboardHeader'
import { KPISection } from './components/KPISection'
import { useDashboardData } from './hooks/useDashboardData'

export default function DashboardPage() {
  const [activeTab, setActiveTab] = useState<TabId>('sessions')
  const [daysRange, setDaysRange] = useState(7)

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
  } = useDashboardData({ daysRange })

  const handleRangeChange = (days: number) => {
    setDaysRange(days)
  }

  return (
    <div className="page-shell">
      <div className="page-backdrop bg-grid-pattern opacity-60" />
      <DashboardHeader
        status={status}
        daysRange={daysRange}
        showRangeDropdown={false}
        onToggleDropdown={() => {}}
        onRangeChange={handleRangeChange}
      />

      <main className="page-frame">
        <div className="page-container">
          {/* Error Banner */}
          {statusError && (
            <div className="mb-5 flex items-center gap-2 rounded-2xl border border-red-800/50 bg-red-900/20 p-4">
              <AlertTriangle className="h-4 w-4 text-red-500" />
              <p className="text-sm text-red-400">
                Unable to connect to backend
              </p>
            </div>
          )}

          {/* BENTO GRID LAYOUT */}
          <div className="grid auto-rows-min grid-cols-12 gap-5">
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
            <div className="panel-surface col-span-12 overflow-hidden p-5 lg:p-6">
              <div className="mb-4 flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
                <div>
                  <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
                    Operational Focus
                  </p>
                  <p className="mt-1 text-sm text-slate-300">
                    Inspect recent sessions, key analytics, and current health
                    from one workspace.
                  </p>
                </div>
                <TabNavigation
                  activeTab={activeTab}
                  onTabChange={setActiveTab}
                />
              </div>
              <div className="mb-4 flex items-center justify-end">
                {activeTab === 'sessions' && (
                  <a
                    href="/sessions"
                    className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500 transition-colors hover:text-slate-300"
                  >
                    View all
                  </a>
                )}
              </div>

              {/* Tab Content */}
              <div className="min-h-[200px]">
                {activeTab === 'sessions' && (
                  <SessionsTabContent
                    sessions={sessionsData?.sessions || []}
                    isLoading={sessionsLoading}
                  />
                )}
                {activeTab === 'analytics' && (
                  <AnalyticsTabContent
                    costsByProject={costsByProject}
                    costsByModel={costsByModel}
                    isLoading={projectLoading || modelLoading}
                    dashboardStats={dashboardStats}
                  />
                )}
                {activeTab === 'health' && (
                  <HealthTabContent stats={dashboardStats} status={status} />
                )}
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>
  )
}
