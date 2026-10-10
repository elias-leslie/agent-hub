export type SessionsEmptyStateKind = 'no-data' | 'no-match'

export function EmptyState({
  kind,
  onClearFilters,
}: {
  kind: SessionsEmptyStateKind
  onClearFilters?: () => void
}) {
  return (
    <div className="space-y-3 py-12 text-center text-sm text-slate-400">
      <p>
        {kind === 'no-data'
          ? 'No sessions recorded yet.'
          : 'No sessions match these filters.'}
      </p>
      {kind === 'no-match' && onClearFilters ? (
        <button
          type="button"
          onClick={onClearFilters}
          className="rounded-md border border-slate-800 bg-slate-950/55 px-3 py-1.5 text-[12px] font-medium text-slate-200 transition-colors hover:border-slate-700 hover:bg-slate-900/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400/50"
        >
          Clear filters
        </button>
      ) : null}
    </div>
  )
}
