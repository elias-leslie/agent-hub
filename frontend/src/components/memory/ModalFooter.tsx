import { cn } from "@/lib/utils";

export function ModalFooter({
  onClose,
  onSave,
  loading,
  saving,
  saved,
}: {
  onClose: () => void;
  onSave: () => void;
  loading: boolean;
  saving: boolean;
  saved: boolean;
}) {
  return (
    <div className="flex items-center justify-end gap-3 p-4 border-t border-slate-200 dark:border-slate-800">
      <button
        onClick={onClose}
        disabled={saving}
        className="px-4 py-2 rounded-lg text-sm font-medium text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-50"
      >
        Cancel
      </button>
      <button
        onClick={onSave}
        disabled={loading || saving || saved}
        className={cn(
          "px-4 py-2 rounded-lg text-sm font-medium text-white disabled:opacity-50 flex items-center gap-2 transition-colors",
          saved ? "bg-emerald-600" : "bg-blue-600 hover:bg-blue-700"
        )}
      >
        {saving ? (
          <>
            <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
            Saving...
          </>
        ) : saved ? (
          "Saved!"
        ) : (
          "Save Changes"
        )}
      </button>
    </div>
  );
}
