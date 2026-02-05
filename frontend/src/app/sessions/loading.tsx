export default function SessionsLoading() {
  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950">
      {/* Header skeleton */}
      <header className="sticky top-0 z-30 border-b border-slate-200 dark:border-slate-800 bg-white/95 dark:bg-slate-900/95 backdrop-blur-sm">
        <div className="px-6 lg:px-8">
          <div className="flex items-center justify-between h-14">
            <div className="flex items-center gap-4">
              <div className="h-6 w-20 bg-slate-200 dark:bg-slate-800 rounded animate-pulse" />
              <div className="h-4 w-16 bg-slate-200 dark:bg-slate-800 rounded animate-pulse" />
            </div>
            <div className="flex items-center gap-2">
              <div className="h-8 w-24 bg-slate-200 dark:bg-slate-800 rounded animate-pulse" />
              <div className="h-8 w-20 bg-slate-200 dark:bg-slate-800 rounded animate-pulse" />
              <div className="h-8 w-16 bg-slate-200 dark:bg-slate-800 rounded animate-pulse" />
            </div>
          </div>
        </div>
      </header>

      <main className="px-6 lg:px-8 py-5">
        <div className="bg-white dark:bg-slate-900 rounded-lg border border-slate-200 dark:border-slate-800 overflow-hidden shadow-sm">
          {/* Table header skeleton */}
          <div className="h-10 bg-slate-50 dark:bg-slate-800/50 border-b border-slate-200 dark:border-slate-700" />

          {/* Table rows skeleton */}
          {Array.from({ length: 10 }).map((_, i) => (
            <div
              key={i}
              className="grid grid-cols-[80px_minmax(120px,1fr)_minmax(140px,1.5fr)_130px_100px_80px_70px_36px] gap-3 px-4 py-3 border-b border-slate-100 dark:border-slate-800/50"
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
      </main>
    </div>
  );
}
