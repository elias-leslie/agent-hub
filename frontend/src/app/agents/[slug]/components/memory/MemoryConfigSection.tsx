import { cn } from "@/lib/utils";
import { MemoryConfig } from "./types";
import { Toggle } from "./Toggle";

interface MemoryConfigSectionProps {
  config: MemoryConfig;
  isCustomEnabled: boolean;
  onUpdateConfig: (updates: Partial<MemoryConfig>) => void;
}

export function MemoryConfigSection({
  config,
  isCustomEnabled,
  onUpdateConfig,
}: MemoryConfigSectionProps) {
  return (
    <div
      className={cn(
        "space-y-5 p-5 rounded-lg border",
        isCustomEnabled
          ? "border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800/50"
          : "border-slate-200 dark:border-slate-700/50 bg-slate-50 dark:bg-slate-800/20 opacity-50 pointer-events-none"
      )}
    >
      <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300 uppercase tracking-wider">
        Injection Settings
      </h3>

      {/* Injection Enabled */}
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-medium text-slate-900 dark:text-slate-200">
            Injection Enabled
          </p>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            Inject memory episodes into agent context
          </p>
        </div>
        <Toggle
          enabled={config.injection_enabled}
          onToggle={() =>
            onUpdateConfig({ injection_enabled: !config.injection_enabled })
          }
          disabled={!isCustomEnabled}
        />
      </div>

      {/* Budget Enforcement */}
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-medium text-slate-900 dark:text-slate-200">
            Budget Enforcement
          </p>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            Enforce token budget limits on injected context
          </p>
        </div>
        <Toggle
          enabled={config.budget_enforcement}
          onToggle={() =>
            onUpdateConfig({ budget_enforcement: !config.budget_enforcement })
          }
          disabled={!isCustomEnabled}
        />
      </div>

      {/* Token Budget Slider */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <label className="text-sm font-medium text-slate-900 dark:text-slate-200">
            Token Budget
          </label>
          <span className="text-sm font-mono text-slate-700 dark:text-slate-300">
            {config.token_budget.toLocaleString()}
          </span>
        </div>
        <input
          type="range"
          min="100"
          max="10000"
          step="100"
          value={config.token_budget}
          onChange={(e) =>
            onUpdateConfig({ token_budget: parseInt(e.target.value) })
          }
          disabled={!isCustomEnabled}
          className="w-full h-2 bg-slate-200 dark:bg-slate-700 rounded-lg appearance-none cursor-pointer accent-blue-600"
        />
        <div className="flex justify-between text-[10px] text-slate-400">
          <span>100</span>
          <span>5,000</span>
          <span>10,000</span>
        </div>
      </div>

      {/* Max Mandates */}
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-medium text-slate-900 dark:text-slate-200">
            Max Mandates
          </p>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            Maximum mandate episodes to inject (0 = unlimited)
          </p>
        </div>
        <input
          type="number"
          min="0"
          value={config.max_mandates}
          onChange={(e) =>
            onUpdateConfig({
              max_mandates: Math.max(0, parseInt(e.target.value) || 0),
            })
          }
          disabled={!isCustomEnabled}
          className="w-20 px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-right focus:outline-none focus:ring-2 focus:ring-blue-500/40"
        />
      </div>

      {/* Max Guardrails */}
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-medium text-slate-900 dark:text-slate-200">
            Max Guardrails
          </p>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            Maximum guardrail episodes to inject (0 = unlimited)
          </p>
        </div>
        <input
          type="number"
          min="0"
          value={config.max_guardrails}
          onChange={(e) =>
            onUpdateConfig({
              max_guardrails: Math.max(0, parseInt(e.target.value) || 0),
            })
          }
          disabled={!isCustomEnabled}
          className="w-20 px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-right focus:outline-none focus:ring-2 focus:ring-blue-500/40"
        />
      </div>

      {/* Reference Index */}
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-medium text-slate-900 dark:text-slate-200">
            Reference Index
          </p>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            Include reference episode index in context
          </p>
        </div>
        <Toggle
          enabled={config.reference_index}
          onToggle={() =>
            onUpdateConfig({ reference_index: !config.reference_index })
          }
          disabled={!isCustomEnabled}
        />
      </div>

      {/* Session Continuity */}
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-medium text-slate-900 dark:text-slate-200">
            Session Continuity
          </p>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            Inject Recent Activity block from prior sessions
          </p>
        </div>
        <Toggle
          enabled={config.continuity_enabled}
          onToggle={() =>
            onUpdateConfig({ continuity_enabled: !config.continuity_enabled })
          }
          disabled={!isCustomEnabled}
        />
      </div>

      {/* Max Sessions (only visible when continuity is enabled) */}
      {config.continuity_enabled && (
        <div className="space-y-2 pl-2">
          <div className="flex items-center justify-between">
            <label className="text-sm font-medium text-slate-900 dark:text-slate-200">
              Max Sessions
            </label>
            <span className="text-sm font-mono text-slate-700 dark:text-slate-300">
              {config.continuity_max_sessions}
            </span>
          </div>
          <input
            type="range"
            min="1"
            max="20"
            step="1"
            value={config.continuity_max_sessions}
            onChange={(e) =>
              onUpdateConfig({
                continuity_max_sessions: parseInt(e.target.value),
              })
            }
            disabled={!isCustomEnabled}
            className="w-full h-2 bg-slate-200 dark:bg-slate-700 rounded-lg appearance-none cursor-pointer accent-violet-600"
          />
          <div className="flex justify-between text-[10px] text-slate-400">
            <span>1</span>
            <span>10</span>
            <span>20</span>
          </div>
        </div>
      )}
    </div>
  );
}
