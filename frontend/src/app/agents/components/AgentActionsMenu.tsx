import { useState } from "react";
import { MoreVertical, Play, Copy, Archive } from "lucide-react";
import type { Agent } from "../lib/types";

export function AgentActionsMenu({
  agent,
  onClone,
  onArchive,
}: {
  agent: Agent;
  onClone?: (agent: Agent) => void;
  onArchive?: (agent: Agent) => void;
}) {
  const [open, setOpen] = useState(false);

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="p-1.5 rounded hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
      >
        <MoreVertical className="h-4 w-4 text-slate-400" />
      </button>

      {open && (
        <>
          <div
            className="fixed inset-0 z-40"
            onClick={() => setOpen(false)}
          />
          <div className="absolute right-0 top-8 z-50 w-40 py-1 bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 shadow-lg">
            <button
              onClick={() => {
                window.location.href = `/agents/${agent.slug}/playground`;
                setOpen(false);
              }}
              className="flex items-center gap-2 w-full px-3 py-2 text-xs text-left hover:bg-slate-50 dark:hover:bg-slate-700"
            >
              <Play className="h-3.5 w-3.5" />
              Playground
            </button>
            <button
              onClick={() => {
                onClone?.(agent);
                setOpen(false);
              }}
              className="flex items-center gap-2 w-full px-3 py-2 text-xs text-left hover:bg-slate-50 dark:hover:bg-slate-700"
            >
              <Copy className="h-3.5 w-3.5" />
              Clone
            </button>
            <div className="border-t border-slate-100 dark:border-slate-700 my-1" />
            <button
              onClick={() => {
                onArchive?.(agent);
                setOpen(false);
              }}
              className="flex items-center gap-2 w-full px-3 py-2 text-xs text-left text-red-600 hover:bg-red-50 dark:hover:bg-red-950/20"
            >
              <Archive className="h-3.5 w-3.5" />
              Archive
            </button>
          </div>
        </>
      )}
    </div>
  );
}
