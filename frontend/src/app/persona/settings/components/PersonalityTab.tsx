import { useState, useEffect, useRef, useCallback } from "react";
import { cn } from "@/lib/utils";
import type { Persona, PersonaUpdate } from "@/types/persona";

interface DocumentSectionProps {
  label: string;
  description: string;
  value: string;
  placeholder: string;
  onSave: (value: string) => void;
  rows?: number;
  textareaClassName?: string;
}

function DocumentSection({ label, description, value, placeholder, onSave, rows = 6, textareaClassName }: DocumentSectionProps) {
  const [localValue, setLocalValue] = useState(value);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => { setLocalValue(value); }, [value]);

  const handleChange = useCallback(
    (newValue: string) => {
      setLocalValue(newValue);
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => onSave(newValue), 2000);
    },
    [onSave],
  );

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
        <span className="text-[10px] text-slate-400">Auto-saves on pause</span>
        <span className="text-[10px] text-slate-400">{localValue.length} chars</span>
      </div>
    </div>
  );
}

interface PersonalityTabProps {
  persona: Persona;
  onUpdate: (fields: PersonaUpdate) => void;
}

export function PersonalityTab({ persona, onUpdate }: PersonalityTabProps) {
  const [personalityValue, setPersonalityValue] = useState(persona.personality || "");
  const personalityTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    setPersonalityValue(persona.personality || "");
  }, [persona.personality]);

  const handlePersonalityChange = useCallback(
    (value: string) => {
      setPersonalityValue(value);
      if (personalityTimerRef.current) clearTimeout(personalityTimerRef.current);
      personalityTimerRef.current = setTimeout(() => {
        onUpdate({ personality: value });
      }, 2000);
    },
    [onUpdate],
  );

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
      <div>
        <textarea
          value={personalityValue}
          onChange={(e) => handlePersonalityChange(e.target.value)}
          rows={14}
          className="w-full px-3 py-2 text-xs font-mono rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-amber-500/40 resize-y min-h-[200px] h-[calc(100vh-28rem)]"
          placeholder="Write your persona's personality in markdown..."
        />
        <div className="flex justify-between mt-1">
          <span className="text-[10px] text-slate-400">Auto-saves on pause</span>
          <span className="text-[10px] text-slate-400">{personalityValue.length} chars</span>
        </div>
      </div>

      {/* User Context */}
      <DocumentSection
        label="User Context"
        description="Knowledge about the user — preferences, patterns, communication style. Updated by the persona as it learns."
        value={persona.user_context || ""}
        placeholder="User preferences and patterns accumulate here..."
        onSave={(v) => onUpdate({ user_context: v })}
        textareaClassName="min-h-[200px] h-[calc(100vh-28rem)]"
      />

    </div>
  );
}
