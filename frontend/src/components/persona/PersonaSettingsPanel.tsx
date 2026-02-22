"use client";

import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { X, Play, Search, Check } from "lucide-react";
import { cn } from "@/lib/utils";
import { useVoicePreferences, type VoiceOption } from "@agent-hub/chat-ui";
import { getApiBaseUrl, buildApiUrl, fetchApi } from "@/lib/api-config";
import type { Persona, PersonaUpdate } from "@/types/persona";

interface PersonaSettingsPanelProps {
  persona: Persona;
  onUpdate: (fields: PersonaUpdate) => Promise<void>;
  onClose: () => void;
}

export function PersonaSettingsPanel({
  persona,
  onUpdate,
  onClose,
}: PersonaSettingsPanelProps) {
  const [nameValue, setNameValue] = useState(persona.name);
  const [personalityValue, setPersonalityValue] = useState(persona.personality || "");
  const [search, setSearch] = useState("");
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

  const handleNameBlur = useCallback(() => {
    if (nameValue.trim() && nameValue !== persona.name) {
      onUpdate({ name: nameValue.trim() });
    }
  }, [nameValue, persona.name, onUpdate]);

  const handlePersonalityChange = useCallback(
    (value: string) => {
      setPersonalityValue(value);
      // Debounced auto-save
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
