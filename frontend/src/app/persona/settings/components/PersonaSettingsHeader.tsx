import Link from "next/link";
import { ArrowLeft, Loader2, CheckCircle2, AlertCircle, BarChart3 } from "lucide-react";
import { cn } from "@/lib/utils";

interface PersonaSettingsHeaderProps {
  hasChanges: boolean;
  isSaving: boolean;
  saveSuccess: boolean;
  saveError: boolean;
  onSave: () => void;
  backHref?: string;
  analyticsHref?: string;
}

export function PersonaSettingsHeader({
  hasChanges,
  isSaving,
  saveSuccess,
  saveError,
  onSave,
  backHref = "/persona",
  analyticsHref = "/persona/analytics",
}: PersonaSettingsHeaderProps) {
  return (
    <header className="flex-shrink-0 border-b border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/80 backdrop-blur-lg z-20">
      <div className="flex items-center justify-between px-4 h-14">
        <div className="flex items-center gap-3">
          <Link
            href={backHref}
            className="p-1.5 rounded-md text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
            title="Back to chat"
          >
            <ArrowLeft className="h-5 w-5" />
          </Link>
          <h1 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
            Persona Settings
          </h1>
        </div>

        <div className="flex items-center gap-3">
          <Link
            href={analyticsHref}
            className="p-1.5 rounded-md text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
            title="Open Jenny analytics"
          >
            <BarChart3 className="h-4.5 w-4.5" />
          </Link>
          {saveSuccess && !hasChanges && (
            <span className="flex items-center gap-1.5 text-xs text-emerald-600 dark:text-emerald-400">
              <CheckCircle2 className="h-3.5 w-3.5" />
              Saved
            </span>
          )}
          {saveError && (
            <span className="flex items-center gap-1.5 text-xs text-red-600 dark:text-red-400">
              <AlertCircle className="h-3.5 w-3.5" />
              Failed to save
            </span>
          )}
          {hasChanges && (
            <button
              onClick={onSave}
              disabled={isSaving}
              className={cn(
                "px-4 py-1.5 text-sm font-medium rounded-lg transition-colors",
                "bg-amber-600 text-white hover:bg-amber-700",
                "disabled:opacity-50 disabled:cursor-not-allowed",
              )}
            >
              {isSaving ? (
                <span className="flex items-center gap-1.5">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  Saving...
                </span>
              ) : (
                "Save Changes"
              )}
            </button>
          )}
        </div>
      </div>
    </header>
  );
}
