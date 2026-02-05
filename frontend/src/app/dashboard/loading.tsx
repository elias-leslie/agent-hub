export default function DashboardLoading() {
  return (
    <div className="min-h-screen bg-slate-950">
      {/* Subtle background pattern */}
      <div className="fixed inset-0 bg-grid-pattern pointer-events-none opacity-30" />

      {/* Header skeleton */}
      <header className="sticky top-0 z-20 border-b border-slate-800/80 bg-slate-900/90 backdrop-blur-xl">
        <div className="px-6 lg:px-8 h-12 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="h-5 w-24 bg-slate-800 rounded animate-pulse" />
            <div className="h-5 w-16 bg-slate-800 rounded-full animate-pulse" />
          </div>
          <div className="h-6 w-20 bg-slate-800 rounded animate-pulse" />
        </div>
      </header>

      <main className="relative px-6 lg:px-8 py-5">
        {/* KPI Cards skeleton */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4 mb-6">
          {Array.from({ length: 6 }).map((_, i) => (
            <div
              key={i}
              className="relative overflow-hidden bg-slate-900/60 border border-slate-800/80 border-l-[3px] border-l-slate-600 rounded-lg p-4"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex-1">
                  <div className="h-3 w-20 bg-slate-800 rounded animate-pulse mb-3" />
                  <div className="h-8 w-16 bg-slate-800 rounded animate-pulse" />
                </div>
                <div className="p-2 rounded-md bg-slate-800/80">
                  <div className="h-4 w-4 bg-slate-700 rounded animate-pulse" />
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* Main content grid skeleton */}
        <div className="grid grid-cols-12 gap-4">
          {/* Chart skeleton */}
          <div className="col-span-8 row-span-2 rounded-xl border border-slate-800/80 bg-slate-900/60 p-5">
            <div className="h-4 w-32 bg-slate-800 rounded animate-pulse mb-4" />
            <div className="h-36 bg-slate-800 rounded animate-pulse" />
            <div className="mt-4 pt-4 border-t border-slate-800/50">
              <div className="h-16 bg-slate-800 rounded animate-pulse" />
            </div>
          </div>

          {/* Provider Health skeleton */}
          <div className="col-span-4 row-span-2 rounded-xl border border-slate-800/80 bg-slate-900/60 p-5">
            <div className="h-4 w-28 bg-slate-800 rounded animate-pulse mb-4" />
            <div className="space-y-2.5">
              <div className="h-16 bg-slate-800 rounded-lg animate-pulse" />
              <div className="h-16 bg-slate-800 rounded-lg animate-pulse" />
            </div>
          </div>

          {/* Tab section skeleton */}
          <div className="col-span-12 rounded-xl border border-slate-800/80 bg-slate-900/60 p-5">
            <div className="flex items-center gap-2 mb-4">
              <div className="h-8 w-24 bg-slate-800 rounded-md animate-pulse" />
              <div className="h-8 w-24 bg-slate-800 rounded-md animate-pulse" />
              <div className="h-8 w-28 bg-slate-800 rounded-md animate-pulse" />
            </div>
            <div className="min-h-[200px] space-y-2">
              {Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="h-12 bg-slate-800 rounded animate-pulse" />
              ))}
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
