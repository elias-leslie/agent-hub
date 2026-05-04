export default function AdminLoading() {
  return (
    <div className="page-shell">
      <div className="page-backdrop bg-grid-pattern opacity-60" />

      {/* Header skeleton */}
      <header className="page-header">
        <div className="page-header-row px-4 lg:px-8">
          <div className="flex items-center gap-4">
            <div className="page-title-icon">
              <div className="w-5 h-5 rounded animate-shimmer" />
            </div>
            <div>
              <div className="h-5 w-32 rounded animate-shimmer mb-1" />
              <div className="h-3 w-40 rounded animate-shimmer" />
            </div>
          </div>
          <div className="flex items-center gap-4">
            <div className="h-8 w-16 rounded-full animate-shimmer" />
            <div className="h-10 w-24 rounded-lg animate-shimmer" />
          </div>
        </div>
      </header>

      <main className="page-frame">
        <div className="page-container space-y-8">
          {/* Stats grid skeleton */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="panel-surface p-5">
                <div className="flex items-center gap-3 mb-3">
                  <div className="p-2 rounded-lg bg-slate-800/80">
                    <div className="w-4 h-4 rounded animate-shimmer" />
                  </div>
                  <div className="h-4 w-20 rounded animate-shimmer" />
                </div>
                <div className="h-8 w-12 rounded animate-shimmer" />
              </div>
            ))}
          </div>

          {/* Kill switches skeleton */}
          <div>
            <div className="flex items-center gap-3 mb-4">
              <div className="h-5 w-5 rounded animate-shimmer" />
              <div className="h-5 w-36 rounded animate-shimmer" />
            </div>
            <div className="space-y-3">
              {Array.from({ length: 3 }).map((_, i) => (
                <div key={i} className="h-16 rounded-xl animate-shimmer" />
              ))}
            </div>
          </div>
        </div>
      </main>
    </div>
  )
}
