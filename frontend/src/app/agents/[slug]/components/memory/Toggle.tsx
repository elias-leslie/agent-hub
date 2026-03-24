import { cn } from "@/lib/utils";

interface ToggleProps {
  enabled: boolean;
  onToggle: () => void;
  disabled?: boolean;
}

export function Toggle({ enabled, onToggle, disabled }: ToggleProps) {
  return (
    <button
      onClick={() => !disabled && onToggle()}
      className={cn(
        "relative inline-flex h-6 w-11 items-center rounded-full transition-colors",
        enabled ? "bg-amber-600" : "bg-slate-300 dark:bg-slate-600",
        disabled && "opacity-50 cursor-not-allowed"
      )}
    >
      <span
        className={cn(
          "inline-block h-4 w-4 transform rounded-full bg-white transition-transform",
          enabled ? "translate-x-6" : "translate-x-1"
        )}
      />
    </button>
  );
}
