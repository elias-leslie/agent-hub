"use client";

import { useState, useEffect } from "react";
import { X, AlertTriangle } from "lucide-react";

export function DeleteModal({
  isOpen,
  onClose,
  onConfirm,
  count,
  isDeleting,
}: {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: () => void;
  count: number;
  isDeleting: boolean;
}) {
  const [acknowledged, setAcknowledged] = useState(false);

  useEffect(() => {
    if (!isOpen) setAcknowledged(false);
  }, [isOpen]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" data-testid="delete-modal">
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-md mx-4 rounded-xl bg-white dark:bg-slate-900 shadow-2xl">
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
            onClick={onClose}
            className="p-1 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 dark:hover:bg-slate-800"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-4 space-y-4">
          <p className="text-sm text-slate-600 dark:text-slate-400">
            This will permanently delete {count} {count === 1 ? "memory" : "memories"} from the
            knowledge graph. This action cannot be undone.
          </p>
          <label className="flex items-start gap-3 cursor-pointer group">
            <input
              type="checkbox"
              checked={acknowledged}
              onChange={(e) => setAcknowledged(e.target.checked)}
              className="mt-1 w-4 h-4 rounded border-slate-300 dark:border-slate-600 text-red-600 focus:ring-red-500"
            />
            <span className="text-sm text-slate-700 dark:text-slate-300">
              I understand this action is permanent
            </span>
          </label>
        </div>

        <div className="flex items-center justify-end gap-3 p-4 border-t border-slate-200 dark:border-slate-800">
          <button
            onClick={onClose}
            disabled={isDeleting}
            className="px-4 py-2 rounded-lg text-sm font-medium text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            onClick={() => acknowledged && onConfirm()}
            disabled={!acknowledged || isDeleting}
            className="px-4 py-2 rounded-lg text-sm font-medium bg-red-600 hover:bg-red-700 text-white disabled:opacity-50 flex items-center gap-2"
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
