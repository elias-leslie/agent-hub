"use client";

import { Trash2, Download, X } from "lucide-react";
import { cn } from "@/lib/utils";

interface BulkActionsToolbarProps {
  selectedCount: number;
  onDelete: () => void;
  onExport: () => void;
  onClearSelection: () => void;
  isDeleting: boolean;
}

export function BulkActionsToolbar({
  selectedCount,
  onDelete,
  onExport,
  onClearSelection,
  isDeleting,
}: BulkActionsToolbarProps) {
  if (selectedCount === 0) return null;

  return (
    <div
      className={cn(
        "fixed bottom-6 left-1/2 -translate-x-1/2 z-40",
        "flex items-center gap-3 px-4 py-3 rounded-xl",
        "bg-slate-900 dark:bg-slate-800 shadow-2xl",
        "border border-slate-700 dark:border-slate-600",
        "animate-in slide-in-from-bottom-4 fade-in duration-200",
      )}
      data-testid="bulk-actions-toolbar"
    >
      {/* Count badge */}
      <span className="flex items-center gap-2 text-sm font-medium text-white">
        <span className="px-2 py-0.5 rounded-full bg-emerald-500 text-xs">
          {selectedCount}
        </span>
        selected
      </span>

      <div className="w-px h-6 bg-slate-600" />

      {/* Delete button */}
      <button
        onClick={onDelete}
        disabled={isDeleting}
        className={cn(
          "flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors",
          "bg-red-600 hover:bg-red-700 text-white",
          "disabled:opacity-50 disabled:cursor-not-allowed",
        )}
        data-testid="bulk-delete-button"
      >
        {isDeleting ? (
          <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
        ) : (
          <Trash2 className="w-4 h-4" />
        )}
        Delete
      </button>

      {/* Export button */}
      <button
        onClick={onExport}
        disabled={isDeleting}
        className={cn(
          "flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors",
          "bg-slate-700 hover:bg-slate-600 text-white",
          "disabled:opacity-50 disabled:cursor-not-allowed",
        )}
        data-testid="bulk-export-button"
      >
        <Download className="w-4 h-4" />
        Export
      </button>

      <div className="w-px h-6 bg-slate-600" />

      {/* Clear selection button */}
      <button
        onClick={onClearSelection}
        disabled={isDeleting}
        className={cn(
          "p-1.5 rounded-lg transition-colors",
          "text-slate-400 hover:text-white hover:bg-slate-700",
          "disabled:opacity-50 disabled:cursor-not-allowed",
        )}
        title="Clear selection"
        data-testid="clear-selection-button"
      >
        <X className="w-4 h-4" />
      </button>
    </div>
  );
}
