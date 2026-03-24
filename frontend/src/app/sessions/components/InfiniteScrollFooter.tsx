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
  total 
}: InfiniteScrollFooterProps) {
  if (isFetchingNextPage) {
    return (
      <div className="flex items-center justify-center py-4 mt-3">
        <div className="flex items-center gap-2 text-slate-400 text-sm">
          <RefreshCw className="w-4 h-4 animate-spin" />
          Loading more sessions...
        </div>
      </div>
    );
  }

  if (!hasNextPage && allSessionsLength > 0) {
    return (
      <div className="flex items-center justify-center py-3 mt-3 text-xs text-slate-500 bg-slate-900/50 rounded-lg">
        Showing all {allSessionsLength} of {total} sessions
      </div>
    );
  }

  return null;
}
