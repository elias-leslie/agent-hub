import { X } from "lucide-react";

interface ModelFilterBadgeProps {
  modelFilter: string;
  onClear: () => void;
}

export function ModelFilterBadge({ modelFilter, onClear }: ModelFilterBadgeProps) {
  if (!modelFilter) return null;

  return (
    <div className="mb-4 flex items-center gap-2">
      <span className="text-xs text-slate-400">Filtered by model:</span>
      <span className="inline-flex items-center gap-1.5 px-2 py-1 rounded-full text-xs font-medium bg-purple-100 dark:bg-purple-900/30 text-purple-300 border border-purple-200 dark:border-purple-800">
        {modelFilter}
        <button
          onClick={onClear}
          className="ml-1 p-0.5 rounded-full hover:bg-purple-200 dark:hover:bg-purple-800 transition-colors"
        >
          <X className="h-3 w-3" />
        </button>
      </span>
    </div>
  );
}
