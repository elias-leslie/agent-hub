export default function MemoryLoading() {
  return (
    <div className="page-shell">
      {/* Header skeleton */}
      <header className="page-header">
        <div className="page-header-row px-4 lg:px-8">
          <div className="flex items-center gap-4">
            <div className="page-title-icon !rounded-xl">
              <div className="w-5 h-5 rounded animate-shimmer" />
            </div>
            <div className="h-6 w-20 rounded animate-shimmer" />
            <div className="hidden sm:flex items-center gap-3">
              <div className="h-4 w-16 rounded animate-shimmer" />
            </div>
          </div>
        </div>
      </header>

      {/* Sub-header skeleton */}
      <div className="px-4 py-3 border-b border-slate-800/70 backdrop-blur-sm">
        <div className="flex items-center gap-3">
          <div className="flex-1 max-w-md h-10 rounded-xl animate-shimmer" />
          <div className="h-10 w-10 rounded-xl animate-shimmer" />
          <div className="h-10 w-10 rounded-xl animate-shimmer" />
        </div>
      </div>

      {/* Table skeleton */}
      <div className="flex-1 overflow-auto">
        <div className="p-4 space-y-2">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="h-12 rounded-xl animate-shimmer" />
          ))}
        </div>
      </div>
    </div>
  )
}
