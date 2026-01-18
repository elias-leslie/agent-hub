"use client";

import { useState } from "react";
import { AlertTriangle, X } from "lucide-react";
import { cn } from "@/lib/utils";

interface DeleteConfirmationModalProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: () => void;
  count: number;
  isDeleting: boolean;
}

export function DeleteConfirmationModal({
  isOpen,
  onClose,
  onConfirm,
  count,
  isDeleting,
}: DeleteConfirmationModalProps) {
  const [acknowledged, setAcknowledged] = useState(false);

  if (!isOpen) return null;

  const handleConfirm = () => {
    if (acknowledged) {
      onConfirm();
    }
  };

  const handleClose = () => {
    setAcknowledged(false);
    onClose();
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      data-testid="delete-modal"
    >
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={handleClose}
      />

      {/* Modal */}
      <div className="relative w-full max-w-md mx-4 rounded-xl bg-white dark:bg-slate-900 shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-slate-200 dark:border-slate-800">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-full bg-red-100 dark:bg-red-900/30">
              <AlertTriangle className="w-5 h-5 text-red-600 dark:text-red-400" />
            </div>
            <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
              Delete {count} {count === 1 ? "Memory" : "Memories"}
            </h2>
          </div>
          <button
            onClick={handleClose}
            className="p-1 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 dark:hover:bg-slate-800"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <div className="p-4 space-y-4">
          <p className="text-sm text-slate-600 dark:text-slate-400">
            This will permanently delete {count} {count === 1 ? "memory" : "memories"} from the knowledge graph.
            This action cannot be undone.
          </p>

          {/* Acknowledgment checkbox */}
          <label className="flex items-start gap-3 cursor-pointer group">
            <input
              type="checkbox"
              checked={acknowledged}
              onChange={(e) => setAcknowledged(e.target.checked)}
              className="mt-1 w-4 h-4 rounded border-slate-300 dark:border-slate-600 text-red-600 focus:ring-red-500"
              data-testid="delete-acknowledgment"
            />
            <span className="text-sm text-slate-700 dark:text-slate-300">
              I understand this action is permanent and cannot be undone
            </span>
          </label>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 p-4 border-t border-slate-200 dark:border-slate-800">
          <button
            onClick={handleClose}
            disabled={isDeleting}
            className={cn(
              "px-4 py-2 rounded-lg text-sm font-medium",
              "text-slate-700 dark:text-slate-300",
              "hover:bg-slate-100 dark:hover:bg-slate-800",
              "disabled:opacity-50 disabled:cursor-not-allowed",
            )}
          >
            Cancel
          </button>
          <button
            onClick={handleConfirm}
            disabled={!acknowledged || isDeleting}
            className={cn(
              "px-4 py-2 rounded-lg text-sm font-medium",
              "bg-red-600 hover:bg-red-700 text-white",
              "disabled:opacity-50 disabled:cursor-not-allowed",
              "flex items-center gap-2",
            )}
          >
            {isDeleting ? (
              <>
                <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                Deleting...
              </>
            ) : (
              "Delete"
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
