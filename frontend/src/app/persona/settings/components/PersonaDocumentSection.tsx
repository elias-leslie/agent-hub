import { AlertCircle, CheckCircle2, Loader2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import type { PersonaAutosaveState } from "@/app/persona/hooks/usePersona";
import { cn } from "@/lib/utils";

interface PersonaDocumentSectionProps {
  label: string;
  description: string;
  value: string;
  placeholder: string;
  onSave: (value: string) => void;
  rows?: number;
  textareaClassName?: string;
  autosave?: PersonaAutosaveState;
}

export function PersonaDocumentSection({
  label,
  description,
  value,
  placeholder,
  onSave,
  rows = 6,
  textareaClassName,
  autosave,
}: PersonaDocumentSectionProps) {
  const [localValue, setLocalValue] = useState(value);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    setLocalValue(value);
  }, [value]);

  useEffect(() => {
    return () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
      }
    };
  }, []);

  const handleChange = useCallback(
    (newValue: string) => {
      setLocalValue(newValue);
      if (timerRef.current) {
        clearTimeout(timerRef.current);
      }
      timerRef.current = setTimeout(() => onSave(newValue), 2000);
    },
    [onSave],
  );

  const saveIndicator = (() => {
    switch (autosave?.status) {
      case "scheduled":
      case "saving":
        return {
          icon: Loader2,
          label: "Saving changes...",
          className: "text-amber-500",
          animate: true,
        };
      case "saved":
        return {
          icon: CheckCircle2,
          label: "Saved",
          className: "text-emerald-500",
          animate: false,
        };
      case "error":
        return {
          icon: AlertCircle,
          label: autosave.errorMessage || "Save failed",
          className: "text-rose-500",
          animate: false,
        };
      default:
        return null;
    }
  })();

  return (
    <div>
      <label className="text-xs font-medium text-slate-600 dark:text-slate-400 mb-1.5 block">
        {label}
      </label>
      <p className="text-xs text-slate-400 dark:text-slate-500 mb-2">{description}</p>
      <textarea
        value={localValue}
        onChange={(e) => handleChange(e.target.value)}
        rows={rows}
        className={cn(
          "w-full px-3 py-2 text-xs font-mono rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-amber-500/40 resize-y",
          textareaClassName,
        )}
        placeholder={placeholder}
      />
      <div className="flex justify-between mt-1">
        <span className="flex items-center gap-1 text-[10px] text-slate-400">
          {saveIndicator ? (
            <>
              <saveIndicator.icon
                className={cn(
                  "h-3 w-3",
                  saveIndicator.className,
                  saveIndicator.animate && "animate-spin",
                )}
              />
              <span className={saveIndicator.className}>{saveIndicator.label}</span>
            </>
          ) : (
            "Auto-saves on pause"
          )}
        </span>
        <span className="text-[10px] text-slate-400">{localValue.length} chars</span>
      </div>
    </div>
  );
}
