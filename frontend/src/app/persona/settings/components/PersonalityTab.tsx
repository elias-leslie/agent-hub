import type { PersonaAutosaveState } from "@/app/persona/hooks/usePersona";
import type { Persona, PersonaUpdate } from "@/types/persona";
import { PersonaDocumentSection } from "./PersonaDocumentSection";

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

interface PersonalityTabProps {
  persona: Persona;
  onUpdate: (fields: PersonaUpdate) => void;
  autosave: PersonaAutosaveState;
}

export function PersonalityTab({ persona, onUpdate, autosave }: PersonalityTabProps) {
  const profile = persona.user_profile ?? {};

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100 mb-1">
          Personality
        </h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Defines core personality, principles, and operating style. Injected into every conversation.
        </p>
      </div>

      {/* Personality Doc */}
      <PersonaDocumentSection
        label="Personality Document"
        description="Markdown document defining the persona's principles, style, and operating posture."
        value={persona.personality || ""}
        placeholder="Write your persona's personality in markdown..."
        onSave={(value) => onUpdate({ personality: value })}
        autosave={autosave}
        rows={14}
        textareaClassName="min-h-[200px] h-[calc(100vh-28rem)]"
      />

      <section className="space-y-4 rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900">
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
                value={profile[field] ?? ""}
                placeholder={placeholder}
                onChange={(event) =>
                  onUpdate({
                    user_profile: {
                      ...profile,
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

      <PersonaDocumentSection
        label="User Notes"
        description="Freeform notes Jenny has learned about the user that do not fit the structured profile."
        value={persona.user_context || ""}
        placeholder="Additional user-specific notes and nuances..."
        onSave={(v) => onUpdate({ user_context: v })}
        autosave={autosave}
        textareaClassName="min-h-[200px] h-[calc(100vh-28rem)]"
      />
    </div>
  );
}
