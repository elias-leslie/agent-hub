import type { SessionsEmptyStateKind } from "../types";

const COPY: Record<SessionsEmptyStateKind, string> = {
  "no-data": "No sessions loaded.",
  "no-match": "No loaded rows match the current filters.",
};

export function EmptyState({
  kind,
  loadedCount = 0,
  totalCount = 0,
  canLoadMore = false,
  onLoadMore,
}: {
  kind: SessionsEmptyStateKind;
  loadedCount?: number;
  totalCount?: number;
  canLoadMore?: boolean;
  onLoadMore?: () => void;
}) {
  return (
    <div className="space-y-3 py-10 text-center text-sm text-slate-500">
      <div>{COPY[kind]}</div>
      {kind === "no-match" && canLoadMore ? (
        <>
          <div className="text-xs text-slate-600">
            Search only covers the {loadedCount} loaded rows so far. Load more results to keep searching {totalCount} total sessions.
          </div>
          <div>
            <button
              type="button"
              onClick={onLoadMore}
              className="rounded-md border border-slate-800/70 bg-slate-950/55 px-3 py-1.5 text-[11px] font-medium text-slate-300 transition-colors hover:border-slate-700 hover:bg-slate-900/60 hover:text-slate-100"
            >
              Load more results
            </button>
          </div>
        </>
      ) : null}
    </div>
  );
}
