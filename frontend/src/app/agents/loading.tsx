export default function AgentsLoading() {
  return (
    <div className="page-shell">
      <div className="page-backdrop bg-grid-pattern opacity-60" />
      {/* Header skeleton */}
      <header className="page-header">
        <div className="page-header-row px-4 lg:px-8">
          <div className="flex items-center gap-4">
            <div className="h-5 w-5 rounded animate-shimmer" />
            <div className="h-6 w-16 rounded animate-shimmer" />
            <div className="h-4 w-12 rounded animate-shimmer" />
          </div>
          <div className="flex items-center gap-2">
            <div className="h-8 w-36 rounded-xl animate-shimmer" />
            <div className="h-8 w-24 rounded-xl animate-shimmer" />
            <div className="h-8 w-20 rounded-xl animate-shimmer" />
            <div className="h-8 w-24 rounded-xl animate-shimmer" />
          </div>
        </div>
      </header>

      <main className="page-frame">
        <div className="page-container">
          {/* Global Instructions Panel skeleton */}
          <div className="mb-5 panel-surface p-4">
            <div className="flex items-center gap-3 mb-3">
              <div className="h-5 w-5 rounded animate-shimmer" />
              <div className="h-5 w-32 rounded animate-shimmer" />
            </div>
            <div className="h-4 w-full rounded animate-shimmer" />
          </div>

          {/* Table skeleton */}
          <div className="table-surface">
            <div className="h-10 border-b border-slate-800/50 animate-shimmer" />
            {Array.from({ length: 5 }).map((_, i) => (
              <div
                key={i}
                className="grid grid-cols-[180px_1fr_100px_70px_130px_130px_130px_80px_40px] gap-3 px-4 py-3 border-b border-slate-800/30"
              >
                <div className="h-4 w-32 rounded animate-shimmer" />
                <div className="h-4 w-48 rounded animate-shimmer" />
                <div className="h-5 w-16 rounded-full animate-shimmer" />
                <div className="h-4 w-8 rounded animate-shimmer" />
                <div className="h-4 w-16 rounded animate-shimmer" />
                <div className="h-4 w-12 rounded animate-shimmer" />
                <div className="h-4 w-12 rounded animate-shimmer" />
                <div className="h-4 w-8 rounded animate-shimmer" />
                <div className="h-4 w-4 rounded animate-shimmer" />
              </div>
            ))}
          </div>
        </div>
      </main>
    </div>
  )
}
