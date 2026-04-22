import { RefreshCw } from "lucide-react";

interface InfiniteScrollFooterProps {
  isFetchingNextPage: boolean;
  hasNextPage: boolean;
  allSessionsLength: number;
  total: number;
}

export function InfiniteScrollFooter({
  isFetchingNextPage,
  hasNextPage,
  allSessionsLength,
  total,
}: InfiniteScrollFooterProps) {
  if (isFetchingNextPage) {
    return (
      <div className="mt-3 flex items-center justify-center rounded-2xl border border-slate-800 bg-slate-950/70 px-4 py-3">
        <div className="flex items-center gap-2 text-sm text-slate-300">
          <RefreshCw className="h-4 w-4 animate-spin" />
          Loading more sessions into the ledger…
        </div>
      </div>
    );
  }

  if (allSessionsLength === 0) {
    return null;
  }

  if (!hasNextPage) {
    return (
      <div className="mt-3 rounded-2xl border border-slate-800 bg-slate-950/70 px-4 py-3 text-center text-xs text-slate-400">
        Loaded all {allSessionsLength} available rows of {total} total sessions.
      </div>
    );
  }

  return (
    <div className="mt-3 rounded-2xl border border-slate-800 bg-slate-950/70 px-4 py-3 text-center text-xs text-slate-500">
      Loaded {allSessionsLength} of {total} sessions so far. Search and filters still apply to the loaded subset.
    </div>
  );
}
