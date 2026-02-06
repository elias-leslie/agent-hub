"use client";

import { useState } from "react";
import { Loader2, Link2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { fetchEpisodeCitations } from "@/lib/memory-api";
import type { EpisodeCitation } from "@/lib/memory-api";

interface CitationsListProps {
  episodeUuid: string;
}

export function CitationsList({ episodeUuid }: CitationsListProps) {
  const [showCitations, setShowCitations] = useState(false);
  const [citations, setCitations] = useState<EpisodeCitation[] | null>(null);
  const [isLoadingCitations, setIsLoadingCitations] = useState(false);

  const handleLoadCitations = async () => {
    if (citations !== null) {
      setShowCitations(!showCitations);
      return;
    }
    setIsLoadingCitations(true);
    setShowCitations(true);
    try {
      const data = await fetchEpisodeCitations(episodeUuid);
      setCitations(data.citations);
    } catch {
      setCitations([]);
    } finally {
      setIsLoadingCitations(false);
    }
  };

  return (
    <>
      <button
        onClick={(e) => { e.stopPropagation(); handleLoadCitations(); }}
        className={cn(
          "flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs font-medium border transition-colors",
          showCitations
            ? "bg-sky-50 dark:bg-sky-900/20 text-sky-600 dark:text-sky-400 border-sky-200 dark:border-sky-800"
            : "bg-slate-50 dark:bg-slate-800/50 text-slate-500 dark:text-slate-400 border-slate-200 dark:border-slate-700 hover:text-sky-600 dark:hover:text-sky-400"
        )}
      >
        {isLoadingCitations ? <Loader2 className="h-3 w-3 animate-spin" /> : <Link2 className="h-3 w-3" />}
        Citations {citations !== null && `(${citations.length})`}
      </button>

      {showCitations && citations !== null && (
        <div className="rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800/50 overflow-hidden">
          {citations.length === 0 ? (
            <p className="p-3 text-xs text-slate-400 italic">No citations recorded yet</p>
          ) : (
            <div className="divide-y divide-slate-100 dark:divide-slate-700/50">
              {citations.map((c, i) => (
                <div key={i} className="px-3 py-2 flex items-center justify-between text-xs">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-slate-600 dark:text-slate-300 truncate max-w-[180px]">
                      {c.session_id ? c.session_id.slice(0, 8) : "—"}
                    </span>
                    {c.project_id && (
                      <span className="px-1.5 py-0.5 rounded text-[10px] bg-slate-100 dark:bg-slate-700 text-slate-500 dark:text-slate-400">
                        {c.project_id}
                      </span>
                    )}
                  </div>
                  <span className="font-mono tabular-nums text-slate-400">
                    {c.created_at ? new Date(c.created_at).toLocaleDateString() : "—"}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </>
  );
}
