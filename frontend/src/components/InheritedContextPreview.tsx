"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ChevronDown,
  ChevronRight,
  Globe2,
  Loader2,
  ExternalLink,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { fetchApi } from "@/lib/api-config";

interface GlobalInstructions {
  id: string;
  content: string;
  enabled: boolean;
  updated_at: string;
}

async function fetchGlobalInstructions(): Promise<GlobalInstructions | null> {
  const res = await fetchApi("/api/global-instructions");
  if (!res.ok) {
    if (res.status === 404) return null;
    throw new Error("Failed to fetch global instructions");
  }
  return res.json();
}

export function InheritedContextPreview() {
  const [isExpanded, setIsExpanded] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ["global-instructions"],
    queryFn: fetchGlobalInstructions,
  });

  if (isLoading) {
    return (
      <div className="mb-4 h-10 rounded-lg bg-slate-100 dark:bg-slate-800/50 animate-pulse" />
    );
  }

  if (!data || !data.enabled || !data.content) {
    return null;
  }

  return (
    <div className="mb-4 rounded-lg border border-amber-200/50 dark:border-amber-800/30 bg-amber-50/30 dark:bg-amber-950/10 overflow-hidden">
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center justify-between px-4 py-2.5 text-left hover:bg-amber-50/50 dark:hover:bg-amber-950/20 transition-colors"
      >
        <div className="flex items-center gap-2">
          {isExpanded ? (
            <ChevronDown className="h-3.5 w-3.5 text-amber-500" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 text-amber-500" />
          )}
          <Globe2 className="h-3.5 w-3.5 text-amber-500" />
          <span className="text-xs font-medium text-amber-700 dark:text-amber-300">
            Inherited Global Context
          </span>
          <span className="text-[10px] text-amber-600/60 dark:text-amber-400/60">
            (read-only)
          </span>
        </div>
        <a
          href="/agents"
          onClick={(e) => e.stopPropagation()}
          className="flex items-center gap-1 text-[10px] text-amber-600 dark:text-amber-400 hover:text-amber-700 dark:hover:text-amber-300 hover:underline"
        >
          Edit
          <ExternalLink className="h-3 w-3" />
        </a>
      </button>

      {isExpanded && (
        <div className="px-4 pb-3 border-t border-amber-200/30 dark:border-amber-800/20">
          <pre className="mt-3 p-3 rounded-md bg-amber-900/5 dark:bg-amber-950/30 text-xs font-mono text-amber-800 dark:text-amber-200/80 whitespace-pre-wrap leading-relaxed max-h-48 overflow-y-auto">
            {data.content}
          </pre>
          <p className="mt-2 text-[10px] text-amber-600/70 dark:text-amber-400/50">
            This content is injected as{" "}
            <code className="px-1 py-0.5 rounded bg-amber-100 dark:bg-amber-900/30">
              &lt;platform_context&gt;
            </code>{" "}
            before this agent&apos;s system prompt.
          </p>
        </div>
      )}
    </div>
  );
}
