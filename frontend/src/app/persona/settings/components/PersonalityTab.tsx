import { useState, useEffect, useRef, useCallback } from "react";
import { BookOpen } from "lucide-react";
import { cn } from "@/lib/utils";
import { fetchApi, buildApiUrl } from "@/lib/api-config";
import type { Persona, PersonaUpdate } from "@/types/persona";

interface JournalEntry {
  id: number;
  entry_date: string;
  content: string;
  entry_type: string;
  created_at: string | null;
}

const ENTRY_TYPE_COLORS: Record<string, string> = {
  observation: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400",
  decision: "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400",
  learning: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400",
  user_insight: "bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-400",
};

interface DocumentSectionProps {
  label: string;
  description: string;
  value: string;
  placeholder: string;
  onSave: (value: string) => void;
  rows?: number;
}

function DocumentSection({ label, description, value, placeholder, onSave, rows = 6 }: DocumentSectionProps) {
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
        className="w-full px-3 py-2 text-xs font-mono rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-amber-500/40 resize-y"
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
  const [journalEntries, setJournalEntries] = useState<JournalEntry[]>([]);
  const [journalLoading, setJournalLoading] = useState(false);

  useEffect(() => {
    setPersonalityValue(persona.personality || "");
  }, [persona.personality]);

  useEffect(() => {
    let cancelled = false;
    setJournalLoading(true);
    fetchApi(buildApiUrl("/api/persona/journal?days_back=30"))
      .then((res) => res.json())
      .then((data) => { if (!cancelled) setJournalEntries(data.entries || []); })
      .catch(() => { if (!cancelled) setJournalEntries([]); })
      .finally(() => { if (!cancelled) setJournalLoading(false); });
    return () => { cancelled = true; };
  }, []);

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
          className="w-full px-3 py-2 text-xs font-mono rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-amber-500/40 resize-y"
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
      />

      {/* Journal (read-only) */}
      <div>
        <div className="flex items-center gap-2 mb-3">
          <BookOpen className="w-3.5 h-3.5 text-slate-400" />
          <label className="text-xs font-medium text-slate-600 dark:text-slate-400">
            Journal
          </label>
          <span className="text-[10px] text-slate-400 ml-auto">
            {journalEntries.length} entries (last 30 days)
          </span>
        </div>
        <p className="text-xs text-slate-400 dark:text-slate-500 mb-2">
          Daily observations, decisions, and learnings. Written by the persona via tools.
        </p>

        <div className="max-h-[320px] overflow-y-auto space-y-2 rounded-lg border border-slate-200 dark:border-slate-700 p-3">
          {journalLoading && (
            <div className="text-center py-4">
              <span className="text-xs text-slate-400">Loading journal...</span>
            </div>
          )}
          {!journalLoading && journalEntries.length === 0 && (
            <div className="text-center py-4">
              <span className="text-xs text-slate-400">No journal entries yet</span>
            </div>
          )}
          {journalEntries.map((entry) => (
            <div
              key={entry.id}
              className="rounded-lg border border-slate-200 dark:border-slate-700 p-2.5"
            >
              <div className="flex items-center gap-2 mb-1">
                <span className="text-[10px] text-slate-400 font-mono">
                  {entry.entry_date}
                </span>
                <span
                  className={cn(
                    "text-[10px] px-1.5 py-0.5 rounded-full font-medium",
                    ENTRY_TYPE_COLORS[entry.entry_type] ||
                      "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400",
                  )}
                >
                  {entry.entry_type}
                </span>
              </div>
              <p className="text-xs text-slate-700 dark:text-slate-300 whitespace-pre-wrap line-clamp-4">
                {entry.content}
              </p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
