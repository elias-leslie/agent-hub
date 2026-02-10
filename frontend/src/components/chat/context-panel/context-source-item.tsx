import { MessageSquare, FileText, Database, Clock, ChevronDown, ChevronUp } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ContextSource } from "./types";
import { formatTokens } from "./utils";

interface ContextSourceItemProps {
  source: ContextSource;
  isExpanded: boolean;
  onToggle: () => void;
}

export function ContextSourceItem({
  source,
  isExpanded,
  onToggle,
}: ContextSourceItemProps) {
  const typeConfig = {
    message: {
      bg: "bg-blue-50 dark:bg-blue-900/20",
      border: "border-blue-200 dark:border-blue-800",
      icon: MessageSquare,
    },
    system: {
      bg: "bg-purple-50 dark:bg-purple-900/20",
      border: "border-purple-200 dark:border-purple-800",
      icon: FileText,
    },
    memory: {
      bg: "bg-emerald-50 dark:bg-emerald-900/20",
      border: "border-emerald-200 dark:border-emerald-800",
      icon: Database,
    },
    summary: {
      bg: "bg-amber-50 dark:bg-amber-900/20",
      border: "border-amber-200 dark:border-amber-800",
      icon: Clock,
    },
  };

  const config = typeConfig[source.type];
  const Icon = config.icon;

  return (
    <div className={cn("rounded border text-xs", config.bg, config.border)}>
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between p-2"
      >
        <div className="flex items-center gap-2">
          <Icon className="h-3 w-3 opacity-60" />
          <span className="font-medium">{source.label}</span>
          {source.tokens && (
            <span className="text-slate-500 dark:text-slate-400">
              {formatTokens(source.tokens)} tokens
            </span>
          )}
        </div>
        {isExpanded ? (
          <ChevronUp className="h-3 w-3 opacity-60" />
        ) : (
          <ChevronDown className="h-3 w-3 opacity-60" />
        )}
      </button>
      {isExpanded && (
        <div className="px-2 pb-2 border-t border-current/10">
          <p className="mt-2 text-slate-600 dark:text-slate-400 whitespace-pre-wrap line-clamp-10">
            {source.content}
          </p>
          {source.type === "summary" && source.originalContent && (
            <details className="mt-2">
              <summary className="cursor-pointer text-blue-600 dark:text-blue-400 hover:underline">
                Show original
              </summary>
              <p className="mt-1 p-2 rounded bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-400 whitespace-pre-wrap">
                {source.originalContent}
              </p>
            </details>
          )}
        </div>
      )}
    </div>
  );
}
