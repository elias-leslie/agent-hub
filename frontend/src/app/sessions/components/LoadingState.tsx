export function LoadingState() {
  return (
    <div className="overflow-hidden rounded-2xl border border-slate-800 bg-slate-950/85 shadow-[0_0_0_1px_rgba(15,23,42,0.35)]">
      <div className="h-12 border-b border-slate-800 bg-slate-900/80" />
      {Array.from({ length: 10 }).map((_, i) => (
        <div
          key={i}
          className="grid grid-cols-[92px_minmax(220px,1.25fr)_minmax(170px,0.95fr)_minmax(240px,1.4fr)_110px_90px_90px_76px] gap-3 border-b border-slate-800/60 px-5 py-4"
        >
          <div className="h-6 w-20 rounded-full bg-slate-800/80 animate-shimmer" />
          <div className="space-y-2">
            <div className="h-4 w-28 rounded bg-slate-800/80 animate-shimmer" />
            <div className="h-3 w-40 rounded bg-slate-800/60 animate-shimmer" />
          </div>
          <div className="space-y-2">
            <div className="h-4 w-24 rounded bg-slate-800/80 animate-shimmer" />
            <div className="h-3 w-28 rounded bg-slate-800/60 animate-shimmer" />
          </div>
          <div className="space-y-2">
            <div className="h-5 w-32 rounded-full bg-slate-800/80 animate-shimmer" />
            <div className="h-3 w-40 rounded bg-slate-800/60 animate-shimmer" />
          </div>
          <div className="ml-auto h-4 w-16 rounded bg-slate-800/80 animate-shimmer" />
          <div className="ml-auto h-4 w-14 rounded bg-slate-800/80 animate-shimmer" />
          <div className="ml-auto h-4 w-12 rounded bg-slate-800/80 animate-shimmer" />
          <div className="ml-auto h-8 w-16 rounded bg-slate-800/80 animate-shimmer" />
        </div>
      ))}
    </div>
  );
}
