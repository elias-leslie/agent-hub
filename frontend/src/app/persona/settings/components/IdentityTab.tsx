import { useState, useCallback, useEffect } from "react";
import { AlertCircle, CheckCircle2, RotateCcw, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { fetchApi, buildApiUrl } from "@/lib/api-config";
import type { Persona, PersonaUpdate } from "@/types/persona";

interface IdentityTabProps {
  persona: Persona;
  onUpdate: (fields: PersonaUpdate) => void;
  onPersonaRefresh?: (updated: Persona) => void;
}

const PHASE_CONFIG = {
  complete: {
    color: "bg-emerald-500",
    pulse: false,
    label: "Onboarded",
    description: "Persona has completed initial setup",
  },
  pending_approval: {
    color: "bg-blue-500",
    pulse: true,
    label: "Pending Approval",
    description: "Onboarding submitted — awaiting dual-model review",
  },
  in_progress: {
    color: "bg-amber-500",
    pulse: true,
    label: "Onboarding In Progress",
    description: "Structured questionnaire is underway",
  },
  not_started: {
    color: "bg-amber-500",
    pulse: false,
    label: "Awaiting First Interaction",
    description: "Bootstrap instructions will be injected on first conversation",
  },
} as const;

const USER_PROFILE_FIELDS = [
  ["user_identity", "User Identity", "Name, preferred address, identity notes"],
  ["work_context", "Work Context", "Role, projects, goals, operating environment"],
  ["communication_style", "Communication Style", "Tone, directness, verbosity, feedback style"],
  ["autonomy_level", "Autonomy Level", "What Jenny should decide alone vs escalate"],
  ["notification_preferences", "Notification Preferences", "Push thresholds, quiet hours, urgency rules"],
  ["timezone", "Timezone", "Canonical timezone, e.g. America/New_York"],
  ["working_schedule", "Working Schedule", "Hours, availability, focus windows"],
  ["priorities_values", "Priorities and Values", "Speed vs quality, docs, testing, tradeoffs"],
  ["tools_and_integrations", "Tools and Integrations", "Preferred services, workflows, constraints"],
  ["boundaries_and_escalation", "Boundaries and Escalation", "No-go zones and mandatory escalations"],
] as const;

export function IdentityTab({ persona, onUpdate, onPersonaRefresh }: IdentityTabProps) {
  const [nameValue, setNameValue] = useState(persona.name);
  const [greetingValue, setGreetingValue] = useState(persona.greeting || "");

  useEffect(() => {
    setNameValue(persona.name);
    setGreetingValue(persona.greeting || "");
  }, [persona.name, persona.greeting]);

  const handleNameBlur = useCallback(() => {
    if (nameValue.trim() && nameValue !== persona.name) {
      onUpdate({ name: nameValue.trim() });
    }
  }, [nameValue, persona.name, onUpdate]);

  const handleGreetingBlur = useCallback(() => {
    if (greetingValue !== (persona.greeting || "")) {
      onUpdate({ greeting: greetingValue });
    }
  }, [greetingValue, persona.greeting, onUpdate]);

  const [resetting, setResetting] = useState(false);
  const [resetState, setResetState] = useState<{
    status: "idle" | "success" | "error";
    message: string | null;
  }>({ status: "idle", message: null });

  const handleResetOnboarding = useCallback(async () => {
    setResetting(true);
    setResetState({ status: "idle", message: null });
    try {
      const res = await fetchApi(buildApiUrl("/api/persona/reset-onboarding"), {
        method: "POST",
      });
      if (!res.ok) {
        throw new Error(`Reset failed with status ${res.status}`);
      }
      const updated = await res.json();
      onPersonaRefresh?.(updated);
      setResetState({
        status: "success",
        message: "Onboarding reset. Bootstrap instructions will be injected into the next new conversation.",
      });
    } catch (err) {
      setResetState({
        status: "error",
        message: err instanceof Error ? err.message : "Failed to reset onboarding",
      });
    } finally {
      setResetting(false);
    }
  }, [onPersonaRefresh]);

  const phase = persona.onboarding_phase || (persona.onboarding_complete ? "complete" : "not_started");
  const config = PHASE_CONFIG[phase] || PHASE_CONFIG.not_started;
  const showReset = phase === "complete" || phase === "in_progress";

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100 mb-1">
          Identity
        </h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Core identity settings for your persona.
        </p>
      </div>

      <div className="space-y-5">
        {/* Display Name */}
        <div>
          <label className="text-xs font-medium text-slate-600 dark:text-slate-400 mb-1.5 block">
            Display Name
          </label>
          <input
            type="text"
            value={nameValue}
            onChange={(e) => setNameValue(e.target.value)}
            onBlur={handleNameBlur}
            onKeyDown={(e) => e.key === "Enter" && handleNameBlur()}
            maxLength={100}
            className="w-full max-w-md px-3 py-2 text-sm rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-amber-500/40"
          />
          <p className="text-[10px] text-slate-400 mt-1">
            Injected into every conversation via the identity tag.
          </p>
        </div>

        {/* Agent Slug */}
        <div>
          <label className="text-xs font-medium text-slate-600 dark:text-slate-400 mb-1.5 block">
            Agent Slug
          </label>
          <div className="px-3 py-2 text-sm rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50 text-slate-500 dark:text-slate-400 max-w-md">
            {persona.agent_slug}
          </div>
        </div>

        {/* Greeting */}
        <div>
          <label className="text-xs font-medium text-slate-600 dark:text-slate-400 mb-1.5 block">
            Greeting Message
          </label>
          <textarea
            value={greetingValue}
            onChange={(e) => setGreetingValue(e.target.value)}
            onBlur={handleGreetingBlur}
            rows={3}
            className="w-full max-w-md px-3 py-2 text-sm rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-amber-500/40 resize-y"
            placeholder="Custom greeting for new sessions..."
          />
        </div>

        <section className="space-y-4 rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900 max-w-4xl">
          <div>
            <h3 className="text-base font-semibold text-slate-900 dark:text-slate-100">
              User Profile
            </h3>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
              Structured user preferences Jenny can rely on consistently at runtime.
            </p>
          </div>
          <div className="grid gap-4">
            {USER_PROFILE_FIELDS.map(([field, label, placeholder]) => (
              <label key={field} className="space-y-2">
                <span className="block text-sm font-medium text-slate-700 dark:text-slate-300">
                  {label}
                </span>
                <textarea
                  value={persona.user_profile?.[field] ?? ""}
                  placeholder={placeholder}
                  onChange={(event) =>
                    onUpdate({
                      user_profile: {
                        ...(persona.user_profile ?? {}),
                        [field]: event.target.value,
                      },
                    })
                  }
                  rows={field === "timezone" ? 2 : 3}
                  className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm outline-none transition focus:border-slate-400 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                />
              </label>
            ))}
          </div>
        </section>

        {/* Onboarding Status */}
        <div className="flex items-center justify-between p-3 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800/50 max-w-md">
          <div className="flex items-center gap-2">
            <span
              className={cn(
                "w-2.5 h-2.5 rounded-full flex-shrink-0",
                config.color,
                config.pulse && "animate-pulse",
              )}
            />
            <div>
              <p className="text-sm font-medium text-slate-700 dark:text-slate-300">
                {config.label}
              </p>
              <p className="text-[10px] text-slate-400">
                {config.description}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {persona.onboarding_attempts > 0 && (
              <span className="text-[10px] font-mono text-slate-400 dark:text-slate-500">
                {persona.onboarding_attempts} attempt{persona.onboarding_attempts !== 1 ? "s" : ""}
              </span>
            )}
            {showReset && (
              <button
                onClick={handleResetOnboarding}
                disabled={resetting}
                className="flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-md text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/20 hover:bg-amber-100 dark:hover:bg-amber-900/40 transition-colors disabled:opacity-50"
                title="Re-run onboarding bootstrap on next conversation"
              >
                {resetting ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <RotateCcw className="h-3 w-3" />
                )}
                Reset
              </button>
            )}
          </div>
        </div>
        {resetState.message && (
          <div
            className={cn(
              "flex max-w-md items-start gap-2 rounded-lg border px-3 py-2 text-xs",
              resetState.status === "success"
                ? "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/30 dark:text-emerald-300"
                : "border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/30 dark:text-rose-300",
            )}
          >
            {resetState.status === "success" ? (
              <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            ) : (
              <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            )}
            <p>{resetState.message}</p>
          </div>
        )}
      </div>
    </div>
  );
}
