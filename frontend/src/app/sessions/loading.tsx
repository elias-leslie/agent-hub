export default function SessionsLoading() {
  return (
    <div className="page-shell">
      <div className="page-backdrop bg-grid-pattern opacity-60" />
      {/* Header skeleton */}
      <header className="page-header">
        <div className="page-header-row px-4 lg:px-8">
          <div className="flex items-center gap-4">
            <div className="h-6 w-20 rounded-lg animate-shimmer" />
            <div className="h-4 w-16 rounded-lg animate-shimmer" />
          </div>
          <div className="flex items-center gap-2">
            <div className="h-8 w-24 rounded-lg animate-shimmer" />
            <div className="h-8 w-20 rounded-lg animate-shimmer" />
            <div className="h-8 w-16 rounded-lg animate-shimmer" />
          </div>
        </div>
      </header>

      <main className="page-frame">
        <div className="page-container">
          <div className="table-surface">
            {/* Table header skeleton */}
            <div className="h-10 border-b border-slate-800/50 animate-shimmer" />

            {/* Table rows skeleton */}
            {Array.from({ length: 10 }).map((_, i) => (
              <div
                key={i}
                className="grid grid-cols-[80px_minmax(120px,1fr)_minmax(140px,1.5fr)_130px_100px_80px_70px_36px] gap-3 px-4 py-3 border-b border-slate-800/30"
              >
                <div className="h-4 w-16 rounded animate-shimmer" />
                <div className="h-4 w-24 rounded animate-shimmer" />
                <div className="h-4 w-32 rounded animate-shimmer" />
                <div className="h-5 w-20 rounded-full animate-shimmer" />
                <div className="h-4 w-16 rounded animate-shimmer ml-auto" />
                <div className="h-4 w-14 rounded animate-shimmer ml-auto" />
                <div className="h-4 w-12 rounded animate-shimmer ml-auto" />
                <div className="h-4 w-4 rounded animate-shimmer ml-auto" />
              </div>
            ))}
          </div>
        </div>
      </main>
    </div>
  )
}
