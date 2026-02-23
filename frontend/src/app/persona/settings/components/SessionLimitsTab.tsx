import { useCallback } from "react";
import { RotateCcw } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Persona, PersonaUpdate } from "@/types/persona";

const RESET_MODES = [
  { value: "off", label: "Off", description: "Sessions persist until manually cleared" },
  { value: "daily", label: "Daily", description: "Reset at a specific hour each day" },
  { value: "idle", label: "Idle", description: "Reset after inactivity timeout" },
] as const;

const HOUR_OPTIONS = Array.from({ length: 24 }, (_, i) => {
  const h = i % 12 || 12;
  const suffix = i < 12 ? "AM" : "PM";
  return { value: i, label: `${h}:00 ${suffix}` };
});

const IDLE_PRESETS = [
  { value: 30, label: "30 min" },
  { value: 60, label: "1 hour" },
  { value: 120, label: "2 hours" },
  { value: 240, label: "4 hours" },
  { value: 480, label: "8 hours" },
];

const DEFAULT_LIMITS: Record<string, { label: string; description: string; value: number }> = {
  max_scheduled_jobs: {
    label: "Max scheduled jobs",
    description: "Maximum active scheduled jobs at any time",
    value: 200,
  },
  max_job_turns: {
    label: "Max turns per job",
    description: "Maximum agent turns per scheduled job execution",
    value: 15,
  },
  max_steers_per_consultation: {
    label: "Max steers per consultation",
    description: "Maximum follow-up messages per consultation session",
    value: 50,
  },
  max_concurrent_consultations: {
    label: "Max concurrent consultations",
    description: "Maximum active consultation sessions at once",
    value: 20,
  },
};

interface SessionLimitsTabProps {
  persona: Persona;
  onUpdate: (fields: PersonaUpdate) => void;
}

export function SessionLimitsTab({ persona, onUpdate }: SessionLimitsTabProps) {
  const mode = persona.session_reset_mode || "off";

  const handleModeChange = useCallback(
    (newMode: "off" | "daily" | "idle") => {
      onUpdate({ session_reset_mode: newMode });
    },
    [onUpdate],
  );

  const handleHourChange = useCallback(
    (hour: number) => {
      onUpdate({ session_reset_hour: hour });
    },
    [onUpdate],
  );

  const handleIdleChange = useCallback(
    (minutes: number) => {
      onUpdate({ session_reset_idle_minutes: minutes });
    },
    [onUpdate],
  );

  const handleLimitChange = useCallback(
    (key: string, value: number) => {
      const current = persona.limits || {};
      onUpdate({ limits: { ...current, [key]: value } });
    },
    [onUpdate, persona.limits],
  );

  const handleLimitReset = useCallback(
    (key: string) => {
      if (!persona.limits) return;
      const next = { ...persona.limits };
      delete next[key];
      onUpdate({ limits: Object.keys(next).length > 0 ? next : null });
    },
    [onUpdate, persona.limits],
  );

  const getLimitValue = (key: string): number => {
    return persona.limits?.[key] ?? DEFAULT_LIMITS[key].value;
  };

  const isLimitCustom = (key: string): boolean => {
    return persona.limits?.[key] != null && persona.limits[key] !== DEFAULT_LIMITS[key].value;
  };

  return (
    <div className="space-y-8">
      {/* Session Reset Section */}
      <div className="space-y-4">
        <div>
          <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100 mb-1">
            Session Reset
          </h2>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Control when conversation sessions automatically reset.
          </p>
        </div>

        {/* Mode Selector — segmented control */}
        <div className="flex gap-1 p-1 rounded-lg bg-slate-100 dark:bg-slate-800 max-w-md">
          {RESET_MODES.map((opt) => (
            <button
              key={opt.value}
              onClick={() => handleModeChange(opt.value)}
              className={cn(
                "flex-1 px-3 py-1.5 text-sm font-medium rounded-md transition-all duration-150",
                mode === opt.value
                  ? "bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100 shadow-sm"
                  : "text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-300",
              )}
            >
              {opt.label}
            </button>
          ))}
        </div>

        {/* Mode Description + Controls */}
        <div className="p-3 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800/50 max-w-md">
          <div className="flex items-center gap-2 mb-2">
            <span
              className={cn(
                "w-2 h-2 rounded-full flex-shrink-0",
                mode === "off" ? "bg-slate-400" : "bg-emerald-500",
              )}
            />
            <p className="text-sm font-medium text-slate-700 dark:text-slate-300">
              {RESET_MODES.find((m) => m.value === mode)?.description}
            </p>
          </div>

          {mode === "daily" && (
            <div className="mt-3 flex items-center justify-between">
              <span className="text-xs text-slate-600 dark:text-slate-400">
                Reset hour
              </span>
              <select
                value={persona.session_reset_hour}
                onChange={(e) => handleHourChange(Number(e.target.value))}
                className="px-2 py-1 text-sm rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-amber-500/40"
              >
                {HOUR_OPTIONS.map((h) => (
                  <option key={h.value} value={h.value}>
                    {h.label}
                  </option>
                ))}
              </select>
            </div>
          )}

          {mode === "idle" && (
            <div className="mt-3 space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs text-slate-600 dark:text-slate-400">
                  Idle timeout
                </span>
                <span className="text-xs font-mono text-slate-500 dark:text-slate-400">
                  {persona.session_reset_idle_minutes} min
                </span>
              </div>
              <div className="flex gap-1">
                {IDLE_PRESETS.map((preset) => (
                  <button
                    key={preset.value}
                    onClick={() => handleIdleChange(preset.value)}
                    className={cn(
                      "flex-1 px-2 py-1 text-xs rounded-md transition-colors",
                      persona.session_reset_idle_minutes === preset.value
                        ? "bg-amber-50 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400 font-medium"
                        : "text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700 border border-slate-200 dark:border-slate-700",
                    )}
                  >
                    {preset.label}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Limits Section */}
      <div className="space-y-4">
        <div>
          <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100 mb-1">
            Limits
          </h2>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Configurable limits for autonomous operations. Leave at defaults for normal use.
          </p>
        </div>

        <div className="space-y-3 max-w-md">
          {Object.entries(DEFAULT_LIMITS).map(([key, config]) => (
            <div
              key={key}
              className="p-3 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800/50"
            >
              <div className="flex items-center justify-between mb-1">
                <label className="text-xs font-medium text-slate-600 dark:text-slate-400">
                  {config.label}
                </label>
                {isLimitCustom(key) && (
                  <button
                    onClick={() => handleLimitReset(key)}
                    className="flex items-center gap-1 text-[10px] text-amber-600 dark:text-amber-400 hover:text-amber-700 dark:hover:text-amber-300 transition-colors"
                  >
                    <RotateCcw className="w-2.5 h-2.5" />
                    Reset
                  </button>
                )}
              </div>
              <p className="text-[10px] text-slate-400 dark:text-slate-500 mb-2">
                {config.description}
              </p>
              <input
                type="number"
                value={getLimitValue(key)}
                onChange={(e) => {
                  const v = Number.parseInt(e.target.value, 10);
                  if (!Number.isNaN(v) && v >= 0) handleLimitChange(key, v);
                }}
                min={0}
                placeholder={String(config.value)}
                className="w-full px-3 py-1.5 text-sm font-mono rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-amber-500/40"
              />
              {!isLimitCustom(key) && (
                <p className="text-[10px] text-slate-400 mt-1">
                  Default: {config.value}
                </p>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
