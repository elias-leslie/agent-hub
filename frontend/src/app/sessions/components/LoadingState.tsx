export function LoadingState() {
  return (
    <div aria-busy="true" aria-label="Loading sessions">
      {Array.from({ length: 12 }).map((_, i) => (
        <div
          // biome-ignore lint/suspicious/noArrayIndexKey: static skeleton rows
          key={i}
          className="flex h-9 items-center gap-3 border-b border-slate-800/50 px-3"
        >
          <div className="h-3 w-16 rounded bg-slate-800/80 animate-shimmer" />
          <div className="h-3 flex-1 rounded bg-slate-800/60 animate-shimmer" />
          <div className="hidden h-3 w-24 rounded bg-slate-800/60 animate-shimmer md:block" />
          <div className="hidden h-3 w-20 rounded bg-slate-800/60 animate-shimmer md:block" />
          <div className="h-3 w-12 rounded bg-slate-800/60 animate-shimmer" />
        </div>
      ))}
    </div>
  )
}
