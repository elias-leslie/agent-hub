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
  const subordinateControlsDisabled = !isCustomEnabled || !config.injection_enabled;

  return (
    <div
      className={cn(
        "space-y-5 p-5 rounded-lg border",
        isCustomEnabled
          ? "border-slate-700 bg-slate-800/50"
          : "border-slate-700/50 bg-slate-800/20 opacity-50 pointer-events-none"
      )}
    >
      <h3 className="text-sm font-semibold text-slate-300 uppercase tracking-wider">
        Injection Settings
      </h3>

      {/* Injection Enabled */}
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-medium text-slate-200">
            Memory Injection
          </p>
          <p className="text-xs text-slate-400">
            Enable durable memory injection for this agent
          </p>
        </div>
        <Toggle
          enabled={config.injection_enabled}
          onToggle={() => {
            if (config.injection_enabled) {
              onUpdateConfig({
                injection_enabled: false,
                include_mandates: false,
                include_guardrails: false,
                include_references: false,
                continuity_enabled: false,
              });
              return;
            }
            onUpdateConfig({ injection_enabled: true });
          }}
          disabled={!isCustomEnabled}
          ariaLabel="Memory Injection"
        />
      </div>

      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-medium text-slate-200">
            Include Mandates
          </p>
          <p className="text-xs text-slate-400">
            Keep universal rule summaries and full mandate expansions eligible
          </p>
        </div>
        <Toggle
          enabled={config.include_mandates}
          onToggle={() =>
            onUpdateConfig({ include_mandates: !config.include_mandates })
          }
          disabled={subordinateControlsDisabled}
          ariaLabel="Include Mandates"
        />
      </div>

      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-medium text-slate-200">
            Include Guardrails
          </p>
          <p className="text-xs text-slate-400">
            Keep anti-pattern and safety memories eligible for injection
          </p>
        </div>
        <Toggle
          enabled={config.include_guardrails}
          onToggle={() =>
            onUpdateConfig({ include_guardrails: !config.include_guardrails })
          }
          disabled={subordinateControlsDisabled}
          ariaLabel="Include Guardrails"
        />
      </div>

      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-medium text-slate-200">
            Include References
          </p>
          <p className="text-xs text-slate-400">
            Allow selected and triggered reference memories in prompt context
          </p>
        </div>
        <Toggle
          enabled={config.include_references}
          onToggle={() =>
            onUpdateConfig({ include_references: !config.include_references })
          }
          disabled={subordinateControlsDisabled}
          ariaLabel="Include References"
        />
      </div>

      {/* Session Continuity */}
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-medium text-slate-200">
            Session Continuity
          </p>
          <p className="text-xs text-slate-400">
            Inject Recent Activity block from prior sessions
          </p>
        </div>
        <Toggle
          enabled={config.continuity_enabled}
          onToggle={() =>
            onUpdateConfig({ continuity_enabled: !config.continuity_enabled })
          }
          disabled={subordinateControlsDisabled}
          ariaLabel="Session Continuity"
        />
      </div>

      {/* Max Sessions (only visible when continuity is enabled) */}
      {config.continuity_enabled && (
        <div className="space-y-2 pl-2">
          <div className="flex items-center justify-between">
            <label className="text-sm font-medium text-slate-200">
              Max Sessions
            </label>
            <span className="text-sm font-mono text-slate-300">
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
            className="w-full h-2 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-violet-600"
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
