import { Database, SearchX } from "lucide-react";
import type { SessionsEmptyStateKind } from "../types";

const CONFIG: Record<
  SessionsEmptyStateKind,
  {
    title: string;
    description: string;
    eyebrow: string;
    Icon: typeof Database;
  }
> = {
  "no-data": {
    title: "No sessions loaded yet",
    description:
      "The ledger is healthy, but the server has not returned any sessions for this query yet.",
    eyebrow: "Empty ledger",
    Icon: Database,
  },
  "no-match": {
    title: "No loaded sessions match the current filters",
    description:
      "Search and filters apply to loaded sessions only. Broaden the filters or load more rows to widen the search surface.",
    eyebrow: "Loaded subset",
    Icon: SearchX,
  },
};

export function EmptyState({ kind }: { kind: SessionsEmptyStateKind }) {
  const { title, description, eyebrow, Icon } = CONFIG[kind];

  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-950/80 px-6 py-12 text-center shadow-[0_0_0_1px_rgba(15,23,42,0.4)]">
      <div className="mx-auto flex max-w-xl flex-col items-center gap-4">
        <div className="rounded-2xl border border-slate-800 bg-slate-900/80 p-3 text-slate-300">
          <Icon className="h-6 w-6" />
        </div>
        <div className="space-y-2">
          <p className="text-[10px] font-mono uppercase tracking-[0.28em] text-slate-500">
            {eyebrow}
          </p>
          <h2 className="text-sm font-semibold text-slate-100">{title}</h2>
          <p className="text-sm leading-6 text-slate-400">{description}</p>
        </div>
      </div>
    </div>
  );
}
