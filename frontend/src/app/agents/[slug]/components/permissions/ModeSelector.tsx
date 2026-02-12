import { cn } from "@/lib/utils";
import { MODE_CONFIG, PermissionMode } from "./constants";

interface ModeSelectorProps {
  currentMode: PermissionMode;
  onModeChange: (mode: PermissionMode) => void;
}

export function ModeSelector({ currentMode, onModeChange }: ModeSelectorProps) {
  return (
    <div className="space-y-3">
      <label className="text-sm font-medium text-slate-300">
        Permission Mode
      </label>
      <div className="grid grid-cols-3 gap-3">
        {(Object.keys(MODE_CONFIG) as PermissionMode[]).map((mode) => {
          const modeConfig = MODE_CONFIG[mode];
          const isActive = currentMode === mode;
          const Icon = modeConfig.icon;

          return (
            <button
              key={mode}
              onClick={() => onModeChange(mode)}
              className={cn(
                "relative flex flex-col items-center gap-2 p-4 rounded-lg border-2 transition-all",
                isActive
                  ? modeConfig.bg
                  : "bg-slate-900/50 border-slate-700 hover:border-slate-600"
              )}
            >
              <Icon
                className={cn(
                  "h-6 w-6",
                  isActive ? modeConfig.color : "text-slate-500"
                )}
              />
              <span
                className={cn(
                  "text-sm font-medium",
                  isActive ? "text-slate-100" : "text-slate-400"
                )}
              >
                {modeConfig.label}
              </span>
              <span
                className={cn(
                  "text-xs text-center",
                  isActive ? "text-slate-400" : "text-slate-500"
                )}
              >
                {modeConfig.description}
              </span>
              {isActive && (
                <div
                  className={cn(
                    "absolute top-2 right-2 h-2 w-2 rounded-full",
                    mode === "yolo"
                      ? "bg-emerald-400"
                      : mode === "ask"
                        ? "bg-amber-400"
                        : "bg-blue-400"
                  )}
                />
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
