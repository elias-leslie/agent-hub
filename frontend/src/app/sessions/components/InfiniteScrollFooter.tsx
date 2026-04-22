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
  if (allSessionsLength === 0) {
    return null;
  }

  if (isFetchingNextPage) {
    return (
      <div className="py-3 text-center text-xs text-slate-500">
        <span className="inline-flex items-center justify-center">
          <RefreshCw className="h-3.5 w-3.5 animate-spin" />
          <span className="sr-only">Loading more rows</span>
        </span>
      </div>
    );
  }

  return (
    <div className="py-3 text-center text-xs text-slate-500">
      {hasNextPage ? `${allSessionsLength} of ${total}` : "End of list"}
    </div>
  );
}
