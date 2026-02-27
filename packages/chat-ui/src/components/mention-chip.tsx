import { X } from "lucide-react";
import { cn } from "../lib/utils";
import type { ModelOption } from "./use-models";

interface MentionChipProps {
  model: ModelOption;
  onRemove: () => void;
}

export function MentionChip({ model, onRemove }: MentionChipProps) {
  const isClaudeProvider = model.provider === "claude";

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 pl-2.5 pr-1.5 py-1 rounded-full text-sm font-medium",
        "transition-all duration-200 ease-out",
        "shadow-sm",
        isClaudeProvider
          ? "bg-gradient-to-r from-amber-900/40 to-orange-900/40 text-amber-200 border border-amber-700/40"
          : "bg-gradient-to-r from-blue-900/40 to-cyan-900/40 text-blue-200 border border-blue-700/40",
      )}
    >
      <span className="flex items-center gap-1">
        <span
          className={cn(
            "w-1.5 h-1.5 rounded-full",
            isClaudeProvider ? "bg-amber-500" : "bg-blue-500"
          )}
        />
        @{model.alias}
      </span>
      <button
        type="button"
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          onRemove();
        }}
        className={cn(
          "p-0.5 rounded-full transition-colors duration-150",
          isClaudeProvider
            ? "hover:bg-amber-600/30"
            : "hover:bg-blue-600/30"
        )}
        aria-label={`Remove @${model.alias}`}
      >
        <X className="w-3 h-3" />
      </button>
    </span>
  );
}
