export default function MemoryLoading() {
  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950">
      {/* Header skeleton */}
      <header className="sticky top-0 z-30 border-b border-slate-200 dark:border-slate-800 bg-white/95 dark:bg-slate-900/95 backdrop-blur-sm">
        <div className="px-4 lg:px-6">
          <div className="flex items-center justify-between h-14">
            <div className="flex items-center gap-4">
              <div className="p-1.5 rounded-lg bg-emerald-100 dark:bg-emerald-900/30">
                <div className="w-5 h-5 bg-emerald-300 dark:bg-emerald-600 rounded animate-pulse" />
              </div>
              <div className="h-6 w-20 bg-slate-200 dark:bg-slate-700 rounded animate-pulse" />
              <div className="hidden sm:flex items-center gap-3">
                <div className="h-4 w-16 bg-slate-200 dark:bg-slate-700 rounded animate-pulse" />
              </div>
            </div>
          </div>
        </div>
      </header>

      {/* Sub-header skeleton */}
      <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900/80">
        <div className="flex items-center gap-3">
          <div className="flex-1 max-w-md h-10 bg-slate-200 dark:bg-slate-700 rounded-lg animate-pulse" />
          <div className="h-10 w-10 bg-slate-200 dark:bg-slate-700 rounded-lg animate-pulse" />
          <div className="h-10 w-10 bg-slate-200 dark:bg-slate-700 rounded-lg animate-pulse" />
        </div>
      </div>

      {/* Table skeleton */}
      <div className="flex-1 overflow-auto">
        <div className="p-4 space-y-2">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="h-12 bg-slate-200 dark:bg-slate-700 rounded animate-pulse" />
          ))}
        </div>
      </div>
    </div>
  );
}
