"use client";

import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { X, Play, Search, Check, BookOpen } from "lucide-react";
import { cn } from "@/lib/utils";
import { useVoicePreferences, type VoiceOption } from "@agent-hub/chat-ui";
import { getApiBaseUrl, buildApiUrl, fetchApi } from "@/lib/api-config";
import type { Persona, PersonaUpdate } from "@/types/persona";

interface JournalEntry {
  id: number;
  entry_date: string;
  content: string;
  entry_type: string;
  created_at: string | null;
}

interface PersonaSettingsPanelProps {
  persona: Persona;
  onUpdate: (fields: PersonaUpdate) => Promise<void>;
  onClose: () => void;
}

/** Reusable debounced textarea section for persona document fields. */
function DocumentSection({
  label,
  description,
  value,
  placeholder,
  onSave,
  rows = 6,
}: {
  label: string;
  description: string;
  value: string;
  placeholder: string;
  onSave: (value: string) => void;
  rows?: number;
}) {
  const [localValue, setLocalValue] = useState(value);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    setLocalValue(value);
  }, [value]);

  const handleChange = useCallback(
    (newValue: string) => {
      setLocalValue(newValue);
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => onSave(newValue), 2000);
    },
    [onSave],
  );

  return (
    <div className="px-4 py-4 border-b border-slate-200 dark:border-slate-800">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-3">
        {label}
      </h3>
      <p className="text-xs text-slate-400 dark:text-slate-500 mb-2">
        {description}
      </p>
      <textarea
        value={localValue}
        onChange={(e) => handleChange(e.target.value)}
        rows={rows}
        className="w-full px-3 py-2 text-xs font-mono rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-1 focus:ring-amber-500 resize-y"
        placeholder={placeholder}
      />
      <div className="flex justify-between mt-1">
        <span className="text-[10px] text-slate-400">Auto-saves on pause</span>
        <span className="text-[10px] text-slate-400">
          {localValue.length} chars
        </span>
      </div>
    </div>
  );
}

const ENTRY_TYPE_COLORS: Record<string, string> = {
  observation: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400",
  decision: "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400",
  learning: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400",
  user_insight: "bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-400",
};

export function PersonaSettingsPanel({
  persona,
  onUpdate,
  onClose,
}: PersonaSettingsPanelProps) {
  const [nameValue, setNameValue] = useState(persona.name);
  const [personalityValue, setPersonalityValue] = useState(persona.personality || "");
  const [search, setSearch] = useState("");
  const [journalEntries, setJournalEntries] = useState<JournalEntry[]>([]);
  const [journalLoading, setJournalLoading] = useState(false);
  const personalityTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const {
    voices,
    selectedVoice,
    ttsEnabled,
    setSelectedVoice,
    setTtsEnabled,
    previewVoice,
  } = useVoicePreferences({
    ttsBaseUrl: getApiBaseUrl() || window.location.origin,
    preferencesEndpoint: buildApiUrl("/api/persona"),
    fetchFn: (url: string, options?: RequestInit) => fetchApi(url, options),
  });

  // Update local state when persona changes externally
  useEffect(() => {
    setNameValue(persona.name);
    setPersonalityValue(persona.personality || "");
  }, [persona.name, persona.personality]);

  // Fetch journal entries
  useEffect(() => {
    let cancelled = false;
    setJournalLoading(true);
    fetchApi(buildApiUrl("/api/persona/journal?days_back=30"))
      .then((res) => res.json())
      .then((data) => {
        if (!cancelled) setJournalEntries(data.entries || []);
      })
      .catch(() => {
        if (!cancelled) setJournalEntries([]);
      })
      .finally(() => {
        if (!cancelled) setJournalLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  const handleNameBlur = useCallback(() => {
    if (nameValue.trim() && nameValue !== persona.name) {
      onUpdate({ name: nameValue.trim() });
    }
  }, [nameValue, persona.name, onUpdate]);

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

  const handleHeartbeatChange = useCallback(
    (minutes: number) => {
      onUpdate({ heartbeat_interval_minutes: minutes });
    },
    [onUpdate],
  );

  // Voice filtering
  const filteredVoices = useMemo(() => {
    const lowerSearch = search.toLowerCase();
    return voices.filter(
      (v) =>
        v.name.toLowerCase().includes(lowerSearch) ||
        v.locale.toLowerCase().includes(lowerSearch) ||
        v.personalities.some((p) => p.toLowerCase().includes(lowerSearch)),
    );
  }, [voices, search]);

  const grouped = useMemo(() => {
    const groups: Record<string, VoiceOption[]> = {};
    for (const v of filteredVoices) {
      const key = v.gender || "Other";
      if (!groups[key]) groups[key] = [];
      groups[key].push(v);
    }
    return groups;
  }, [filteredVoices]);

  return (
    <div className="fixed inset-y-0 right-0 w-96 bg-white dark:bg-slate-900 border-l border-slate-200 dark:border-slate-800 shadow-2xl z-50 flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-4 h-14 border-b border-slate-200 dark:border-slate-800 flex-shrink-0">
        <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
          Persona Settings
        </h2>
        <button
          onClick={onClose}
          className="p-1.5 rounded-md text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {/* Scrollable content */}
      <div className="flex-1 overflow-y-auto">
        {/* Identity Section */}
        <div className="px-4 py-4 border-b border-slate-200 dark:border-slate-800">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-3">
            Identity
          </h3>
          <div className="space-y-3">
            <div>
              <label className="text-xs text-slate-500 dark:text-slate-400 mb-1 block">
                Display Name
              </label>
              <input
                type="text"
                value={nameValue}
                onChange={(e) => setNameValue(e.target.value)}
                onBlur={handleNameBlur}
                onKeyDown={(e) => e.key === "Enter" && handleNameBlur()}
                maxLength={100}
                className="w-full px-3 py-1.5 text-sm rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-1 focus:ring-amber-500"
              />
            </div>
            <div>
              <label className="text-xs text-slate-500 dark:text-slate-400 mb-1 block">
                Agent Slug
              </label>
              <div className="px-3 py-1.5 text-sm rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50 text-slate-500 dark:text-slate-400">
                {persona.agent_slug}
              </div>
            </div>
            {/* Onboarding indicator */}
            <div className="flex items-center gap-2">
              <span className={cn(
                "w-2 h-2 rounded-full",
                persona.onboarding_complete ? "bg-emerald-500" : "bg-amber-500 animate-pulse",
              )} />
              <span className="text-xs text-slate-500 dark:text-slate-400">
                {persona.onboarding_complete ? "Onboarded" : "Awaiting first interaction"}
              </span>
            </div>
          </div>
        </div>

        {/* Personality Section */}
        <div className="px-4 py-4 border-b border-slate-200 dark:border-slate-800">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-3">
            Personality
          </h3>
          <p className="text-xs text-slate-400 dark:text-slate-500 mb-2">
            Defines your persona&apos;s personality, principles, and operating style.
            Injected into every conversation as core identity.
          </p>
          <textarea
            value={personalityValue}
            onChange={(e) => handlePersonalityChange(e.target.value)}
            rows={12}
            className="w-full px-3 py-2 text-xs font-mono rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-1 focus:ring-amber-500 resize-y"
            placeholder="Write your persona's personality in markdown..."
          />
          <div className="flex justify-between mt-1">
            <span className="text-[10px] text-slate-400">
              Auto-saves on pause
            </span>
            <span className="text-[10px] text-slate-400">
              {personalityValue.length} chars
            </span>
          </div>
        </div>

        {/* Heartbeat Instructions */}
        <DocumentSection
          label="Heartbeat Instructions"
          description="Custom instructions for autonomous heartbeat checks. Defines what to monitor and when to alert."
          value={persona.heartbeat_instructions || ""}
          placeholder="Describe what the persona should check during heartbeats..."
          onSave={(v) => onUpdate({ heartbeat_instructions: v })}
        />

        {/* User Context */}
        <DocumentSection
          label="User Context"
          description="Knowledge about the user — preferences, patterns, communication style. Updated by the persona as it learns."
          value={persona.user_context || ""}
          placeholder="User preferences and patterns accumulate here..."
          onSave={(v) => onUpdate({ user_context: v })}
        />

        {/* Tools Guidance */}
        <DocumentSection
          label="Tools Guidance"
          description="Additional guidance for tool usage — custom scripts, project-specific commands, workflow preferences."
          value={persona.tools_guidance || ""}
          placeholder="Custom tool usage instructions..."
          onSave={(v) => onUpdate({ tools_guidance: v })}
          rows={4}
        />

        {/* Journal Section */}
        <div className="px-4 py-4 border-b border-slate-200 dark:border-slate-800">
          <div className="flex items-center gap-2 mb-3">
            <BookOpen className="w-3.5 h-3.5 text-slate-400" />
            <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
              Journal
            </h3>
            <span className="text-[10px] text-slate-400 ml-auto">
              {journalEntries.length} entries
            </span>
          </div>
          <p className="text-xs text-slate-400 dark:text-slate-500 mb-2">
            Daily observations, decisions, and learnings. Written by the persona via tools.
          </p>

          <div className="max-h-[240px] overflow-y-auto space-y-2">
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

        {/* Voice Section */}
        <div className="px-4 py-4 border-b border-slate-200 dark:border-slate-800">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-3">
            Voice
          </h3>

          {/* TTS Toggle */}
          <div className="flex items-center justify-between mb-3">
            <span className="text-sm text-slate-700 dark:text-slate-300">
              Text-to-speech
            </span>
            <button
              onClick={() => setTtsEnabled(!ttsEnabled)}
              className={cn(
                "relative w-10 h-5 rounded-full transition-colors duration-200",
                ttsEnabled
                  ? "bg-amber-500"
                  : "bg-slate-300 dark:bg-slate-600",
              )}
            >
              <span
                className={cn(
                  "absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform duration-200",
                  ttsEnabled && "translate-x-5",
                )}
              />
            </button>
          </div>

          {/* Voice Search */}
          <div className="relative mb-2">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search voices..."
              className="w-full pl-8 pr-3 py-1.5 text-sm rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-1 focus:ring-amber-500"
            />
          </div>

          {/* Voice List */}
          <div className="max-h-[200px] overflow-y-auto rounded-lg border border-slate-200 dark:border-slate-700">
            {Object.entries(grouped).map(([gender, groupVoices]) => (
              <div key={gender}>
                <div className="px-3 py-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400 bg-slate-50 dark:bg-slate-800/50 sticky top-0">
                  {gender}
                </div>
                {groupVoices.map((voice) => (
                  <button
                    key={voice.id}
                    onClick={() => setSelectedVoice(voice.id)}
                    className={cn(
                      "w-full flex items-center gap-2 px-3 py-1.5 text-left hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors",
                      voice.id === selectedVoice &&
                        "bg-amber-50 dark:bg-amber-900/20",
                    )}
                  >
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        previewVoice(voice.id);
                      }}
                      className="flex-shrink-0 p-0.5 rounded text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
                    >
                      <Play className="w-3 h-3" />
                    </button>
                    <div className="flex-1 min-w-0">
                      <span className="text-xs font-medium text-slate-900 dark:text-slate-100 truncate block">
                        {voice.name}
                      </span>
                      {voice.personalities.length > 0 && (
                        <span className="text-[10px] text-slate-400">
                          {voice.personalities.slice(0, 2).join(", ")}
                        </span>
                      )}
                    </div>
                    {voice.id === selectedVoice && (
                      <Check className="w-3.5 h-3.5 text-amber-500 flex-shrink-0" />
                    )}
                  </button>
                ))}
              </div>
            ))}
            {filteredVoices.length === 0 && (
              <div className="px-3 py-4 text-center text-xs text-slate-400">
                No voices found
              </div>
            )}
          </div>
        </div>

        {/* Heartbeat Section */}
        <div className="px-4 py-4">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-3">
            Heartbeat
          </h3>
          <div className="flex items-center justify-between">
            <span className="text-sm text-slate-700 dark:text-slate-300">
              Check-in interval
            </span>
            <select
              value={persona.heartbeat_interval_minutes}
              onChange={(e) => handleHeartbeatChange(Number(e.target.value))}
              className="px-2 py-1 text-sm rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100"
            >
              <option value={15}>15 min</option>
              <option value={30}>30 min</option>
              <option value={60}>1 hour</option>
              <option value={120}>2 hours</option>
              <option value={240}>4 hours</option>
              <option value={0}>Off</option>
            </select>
          </div>
          <p className="text-[10px] text-slate-400 mt-1">
            How often {persona.name} runs autonomous system checks
          </p>
        </div>
      </div>
    </div>
  );
}
