export function LoadingState() {
  return (
    <div className="bg-slate-900 rounded-lg border border-slate-800 overflow-hidden shadow-sm">
      {/* Skeleton header */}
      <div className="h-10 bg-slate-800/50 border-b border-slate-700" />
      {/* Skeleton rows */}
      {Array.from({ length: 10 }).map((_, i) => (
        <div
          key={i}
          className="grid grid-cols-[80px_minmax(120px,1fr)_minmax(140px,1.5fr)_130px_100px_80px_70px_36px] gap-3 px-4 py-3 border-b border-slate-800/50"
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
  );
}
