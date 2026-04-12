import { cn } from "@/lib/utils";
import { MemoryConfig } from "./types";
import { Toggle } from "./Toggle";

const CONSUMER_PROFILE_SUGGESTIONS = [
  "agent_general",
  "agent_visual",
  "agent_coding",
  "agent_operator",
  "agent_promptops",
  "agent_preview",
  "agent_runtime",
  "claude_session_start",
  "codex_startup",
] as const;

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
  const referenceIndexDisabled =
    subordinateControlsDisabled || !config.include_references;
  const profileInputsDisabled = !isCustomEnabled;

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

      <div className="space-y-3 rounded-lg border border-slate-700/70 bg-slate-900/40 p-4">
        <div>
          <p className="text-sm font-medium text-slate-200">
            Context Routing
          </p>
          <p className="text-xs text-slate-400">
            Set role-fit memory budget and rendering. Leave blank to inherit defaults.
          </p>
        </div>

        <div className="grid gap-3 md:grid-cols-2">
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-slate-400">
              Runtime Profile Override
            </label>
            <input
              type="text"
              list="memory-consumer-profiles"
              aria-label="Runtime Profile Override"
              value={config.runtime_consumer_profile ?? ""}
              onChange={(e) =>
                onUpdateConfig({
                  runtime_consumer_profile: e.target.value.trim() || undefined,
                })
              }
              disabled={profileInputsDisabled}
              placeholder="agent_coding"
              className="w-full px-3 py-2 rounded-lg border border-slate-700 bg-slate-800 text-sm focus:outline-none focus:ring-2 focus:ring-amber-500/40 placeholder:text-slate-500"
            />
            <p className="text-[11px] text-slate-500">
              Live completion surface. Main switch for no-more-no-less policy routing.
            </p>
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-medium text-slate-400">
              Preview Profile Override
            </label>
            <input
              type="text"
              list="memory-consumer-profiles"
              aria-label="Preview Profile Override"
              value={config.preview_consumer_profile ?? ""}
              onChange={(e) =>
                onUpdateConfig({
                  preview_consumer_profile: e.target.value.trim() || undefined,
                })
              }
              disabled={profileInputsDisabled}
              placeholder="Leave blank to mirror runtime"
              className="w-full px-3 py-2 rounded-lg border border-slate-700 bg-slate-800 text-sm focus:outline-none focus:ring-2 focus:ring-amber-500/40 placeholder:text-slate-500"
            />
            <p className="text-[11px] text-slate-500">
              Preview/debug surface. Blank falls back to runtime profile.
            </p>
          </div>

          <div className="space-y-1.5 md:col-span-2">
            <label className="text-xs font-medium text-slate-400">
              Shared Profile Fallback
            </label>
            <input
              type="text"
              list="memory-consumer-profiles"
              aria-label="Shared Profile Fallback"
              value={config.consumer_profile ?? ""}
              onChange={(e) =>
                onUpdateConfig({
                  consumer_profile: e.target.value.trim() || undefined,
                })
              }
              disabled={profileInputsDisabled}
              placeholder="Optional fallback for runtime + preview"
              className="w-full px-3 py-2 rounded-lg border border-slate-700 bg-slate-800 text-sm focus:outline-none focus:ring-2 focus:ring-amber-500/40 placeholder:text-slate-500"
            />
            <p className="text-[11px] text-slate-500">
              Used only when a surface-specific override is unset.
            </p>
          </div>
        </div>
      </div>

      <datalist id="memory-consumer-profiles">
        {CONSUMER_PROFILE_SUGGESTIONS.map((profile) => (
          <option key={profile} value={profile} />
        ))}
      </datalist>

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
                reference_index_enabled: false,
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
            Project Index Context
          </p>
          <p className="text-xs text-slate-400">
            Inject compact canonical `.index.yaml` project metadata for project-scoped work
          </p>
        </div>
        <Toggle
          enabled={config.project_index_enabled}
          onToggle={() =>
            onUpdateConfig({
              project_index_enabled: !config.project_index_enabled,
            })
          }
          disabled={!isCustomEnabled}
          ariaLabel="Project Index Context"
        />
      </div>

      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-medium text-slate-200">
            Tool Capability Context
          </p>
          <p className="text-xs text-slate-400">
            Inject compact wrapper-tool discovery hints and canonical `--help` entrypoints
          </p>
        </div>
        <Toggle
          enabled={config.tool_capabilities_enabled}
          onToggle={() =>
            onUpdateConfig({
              tool_capabilities_enabled: !config.tool_capabilities_enabled,
            })
          }
          disabled={!isCustomEnabled}
          ariaLabel="Tool Capability Context"
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

      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-medium text-slate-200">
            Passive Reference Index
          </p>
          <p className="text-xs text-slate-400">
            Inject a lightweight lookup catalog before pulling full reference details
          </p>
        </div>
        <Toggle
          enabled={config.reference_index_enabled}
          onToggle={() =>
            onUpdateConfig({
              reference_index_enabled: !config.reference_index_enabled,
            })
          }
          disabled={referenceIndexDisabled}
          ariaLabel="Passive Reference Index"
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
