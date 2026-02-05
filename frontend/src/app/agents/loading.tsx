export default function AgentsLoading() {
  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950">
      {/* Header skeleton */}
      <header className="sticky top-0 z-30 border-b border-slate-200 dark:border-slate-800 bg-white/95 dark:bg-slate-900/95 backdrop-blur-sm">
        <div className="px-6 lg:px-8">
          <div className="flex items-center justify-between h-14">
            <div className="flex items-center gap-4">
              <div className="h-5 w-5 bg-slate-200 dark:bg-slate-700 rounded animate-pulse" />
              <div className="h-6 w-16 bg-slate-200 dark:bg-slate-700 rounded animate-pulse" />
              <div className="h-4 w-12 bg-slate-200 dark:bg-slate-700 rounded animate-pulse" />
            </div>
            <div className="flex items-center gap-2">
              <div className="h-8 w-36 bg-slate-200 dark:bg-slate-700 rounded-md animate-pulse" />
              <div className="h-8 w-24 bg-slate-200 dark:bg-slate-700 rounded-md animate-pulse" />
              <div className="h-8 w-20 bg-slate-200 dark:bg-slate-700 rounded-md animate-pulse" />
              <div className="h-8 w-24 bg-blue-200 dark:bg-blue-900/50 rounded-md animate-pulse" />
            </div>
          </div>
        </div>
      </header>

      <main className="px-6 lg:px-8 py-5">
        {/* Global Instructions Panel skeleton */}
        <div className="mb-5 p-4 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900">
          <div className="flex items-center gap-3 mb-3">
            <div className="h-5 w-5 bg-slate-200 dark:bg-slate-700 rounded animate-pulse" />
            <div className="h-5 w-32 bg-slate-200 dark:bg-slate-700 rounded animate-pulse" />
          </div>
          <div className="h-4 w-full bg-slate-200 dark:bg-slate-700 rounded animate-pulse" />
        </div>

        {/* Table skeleton */}
        <div className="bg-white dark:bg-slate-900 rounded-lg border border-slate-200 dark:border-slate-800 overflow-hidden shadow-sm">
          <div className="h-10 bg-slate-50 dark:bg-slate-800/50 border-b border-slate-200 dark:border-slate-700" />
          {Array.from({ length: 5 }).map((_, i) => (
            <div
              key={i}
              className="grid grid-cols-[180px_1fr_100px_70px_130px_130px_130px_80px_40px] gap-3 px-4 py-3 border-b border-slate-100 dark:border-slate-800/50"
            >
              <div className="h-4 w-32 rounded bg-slate-200 dark:bg-slate-700 animate-pulse" />
              <div className="h-4 w-48 rounded bg-slate-200 dark:bg-slate-700 animate-pulse" />
              <div className="h-5 w-16 rounded-full bg-slate-200 dark:bg-slate-700 animate-pulse" />
              <div className="h-4 w-8 rounded bg-slate-200 dark:bg-slate-700 animate-pulse" />
              <div className="h-4 w-16 rounded bg-slate-200 dark:bg-slate-700 animate-pulse" />
              <div className="h-4 w-12 rounded bg-slate-200 dark:bg-slate-700 animate-pulse" />
              <div className="h-4 w-12 rounded bg-slate-200 dark:bg-slate-700 animate-pulse" />
              <div className="h-4 w-8 rounded bg-slate-200 dark:bg-slate-700 animate-pulse" />
              <div className="h-4 w-4 rounded bg-slate-200 dark:bg-slate-700 animate-pulse" />
            </div>
          ))}
        </div>
      </main>
    </div>
  );
}
