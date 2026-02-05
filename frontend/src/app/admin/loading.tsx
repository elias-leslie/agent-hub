export default function AdminLoading() {
  return (
    <div className="min-h-screen bg-slate-950">
      {/* Grid pattern overlay */}
      <div
        className="fixed inset-0 pointer-events-none opacity-[0.015]"
        style={{
          backgroundImage: `linear-gradient(rgba(251,191,36,0.5) 1px, transparent 1px),
                            linear-gradient(90deg, rgba(251,191,36,0.5) 1px, transparent 1px)`,
          backgroundSize: "64px 64px",
        }}
      />

      {/* Header skeleton */}
      <header className="sticky top-0 z-20 border-b border-slate-800 bg-slate-950/90 backdrop-blur-xl">
        <div className="px-6 lg:px-8">
          <div className="flex items-center justify-between h-16">
            <div className="flex items-center gap-4">
              <div className="p-2.5 rounded-xl bg-gradient-to-br from-amber-500/20 to-orange-600/20 border border-amber-500/30">
                <div className="w-6 h-6 bg-amber-400/50 rounded animate-pulse" />
              </div>
              <div>
                <div className="h-5 w-32 bg-slate-800 rounded animate-pulse mb-1" />
                <div className="h-3 w-40 bg-slate-800 rounded animate-pulse" />
              </div>
            </div>
            <div className="flex items-center gap-4">
              <div className="h-8 w-16 bg-emerald-950/50 rounded-full animate-pulse" />
              <div className="h-10 w-24 bg-slate-800 rounded-lg animate-pulse" />
            </div>
          </div>
        </div>
      </header>

      <main className="px-6 lg:px-8 py-8 space-y-8 relative">
        {/* Stats grid skeleton */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <div
              key={i}
              className="p-5 rounded-xl bg-gradient-to-br from-slate-900/80 to-slate-900/40 border border-slate-800"
            >
              <div className="flex items-center gap-3 mb-3">
                <div className="p-2 rounded-lg bg-slate-800">
                  <div className="w-4 h-4 bg-slate-700 rounded animate-pulse" />
                </div>
                <div className="h-4 w-20 bg-slate-800 rounded animate-pulse" />
              </div>
              <div className="h-8 w-12 bg-slate-800 rounded animate-pulse" />
            </div>
          ))}
        </div>

        {/* Kill switches skeleton */}
        <div>
          <div className="flex items-center gap-3 mb-4">
            <div className="h-5 w-5 bg-emerald-900/50 rounded animate-pulse" />
            <div className="h-5 w-36 bg-slate-800 rounded animate-pulse" />
          </div>
          <div className="space-y-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="h-16 bg-slate-800/50 rounded-xl animate-pulse" />
            ))}
          </div>
        </div>
      </main>
    </div>
  );
}
