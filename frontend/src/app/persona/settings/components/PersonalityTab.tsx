import type { PersonaAutosaveState } from "@/app/persona/hooks/usePersona";
import type { Persona, PersonaUpdate } from "@/types/persona";
import { PersonaDocumentSection } from "./PersonaDocumentSection";

interface PersonalityTabProps {
  persona: Persona;
  onUpdate: (fields: PersonaUpdate) => void;
  autosave: PersonaAutosaveState;
}

export function PersonalityTab({ persona, onUpdate, autosave }: PersonalityTabProps) {
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

      {/* User Context */}
      <PersonaDocumentSection
        label="User Context"
        description="Knowledge about the user — preferences, patterns, communication style. Updated by the persona as it learns."
        value={persona.user_context || ""}
        placeholder="User preferences and patterns accumulate here..."
        onSave={(v) => onUpdate({ user_context: v })}
        autosave={autosave}
        textareaClassName="min-h-[200px] h-[calc(100vh-28rem)]"
      />

    </div>
  );
}
