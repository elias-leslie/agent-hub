import type { SessionsEmptyStateKind } from "../types";

const COPY: Record<SessionsEmptyStateKind, string> = {
  "no-data": "No sessions loaded.",
  "no-match": "No loaded rows match the current filters.",
};

export function EmptyState({ kind }: { kind: SessionsEmptyStateKind }) {
  return (
    <div className="py-10 text-center text-sm text-slate-500">
      {COPY[kind]}
    </div>
  );
}
