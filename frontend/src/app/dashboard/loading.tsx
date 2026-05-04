export default function DashboardLoading() {
  return (
    <div className="page-shell">
      <div className="page-backdrop bg-grid-pattern opacity-60" />

      {/* Header skeleton */}
      <header className="page-header">
        <div className="page-header-row px-4 lg:px-8">
          <div className="flex items-center gap-3">
            <div className="h-5 w-24 rounded-lg animate-shimmer" />
            <div className="h-5 w-16 rounded-full animate-shimmer" />
          </div>
          <div className="h-6 w-20 rounded-lg animate-shimmer" />
        </div>
      </header>

      <main className="page-frame">
        <div className="page-container">
          {/* KPI Cards skeleton */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4 mb-6">
            {Array.from({ length: 6 }).map((_, i) => (
              <div
                key={i}
                className="relative overflow-hidden bg-slate-900/60 border border-slate-800/80 border-l-[3px] border-l-slate-600 rounded-2xl p-4"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1">
                    <div className="h-3 w-20 rounded animate-shimmer mb-3" />
                    <div className="h-8 w-16 rounded animate-shimmer" />
                  </div>
                  <div className="p-2 rounded-md bg-slate-800/80">
                    <div className="h-4 w-4 rounded animate-shimmer" />
                  </div>
                </div>
              </div>
            ))}
          </div>

          {/* Main content grid skeleton */}
          <div className="grid grid-cols-12 gap-4">
            {/* Chart skeleton */}
            <div className="col-span-8 row-span-2 panel-surface p-5">
              <div className="h-4 w-32 rounded animate-shimmer mb-4" />
              <div className="h-36 rounded-xl animate-shimmer" />
              <div className="mt-4 pt-4 border-t border-slate-800/50">
                <div className="h-16 rounded animate-shimmer" />
              </div>
            </div>

            {/* Provider Health skeleton */}
            <div className="col-span-4 row-span-2 panel-surface p-5">
              <div className="h-4 w-28 rounded animate-shimmer mb-4" />
              <div className="space-y-2.5">
                <div className="h-16 rounded-lg animate-shimmer" />
                <div className="h-16 rounded-lg animate-shimmer" />
              </div>
            </div>

            {/* Tab section skeleton */}
            <div className="col-span-12 panel-surface p-5">
              <div className="flex items-center gap-2 mb-4">
                <div className="h-8 w-24 rounded-md animate-shimmer" />
                <div className="h-8 w-24 rounded-md animate-shimmer" />
                <div className="h-8 w-28 rounded-md animate-shimmer" />
              </div>
              <div className="min-h-[200px] space-y-2">
                {Array.from({ length: 5 }).map((_, i) => (
                  <div key={i} className="h-12 rounded animate-shimmer" />
                ))}
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>
  )
}
