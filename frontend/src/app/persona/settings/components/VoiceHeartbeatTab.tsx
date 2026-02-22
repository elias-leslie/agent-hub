import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { Play, Search, Check } from "lucide-react";
import { cn } from "@/lib/utils";
import { useVoicePreferences, type VoiceOption } from "@agent-hub/chat-ui";
import { getApiBaseUrl, buildApiUrl, fetchApi } from "@/lib/api-config";
import type { Persona, PersonaUpdate } from "@/types/persona";

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

interface VoiceHeartbeatTabProps {
  persona: Persona;
  onUpdate: (fields: PersonaUpdate) => void;
}

export function VoiceHeartbeatTab({ persona, onUpdate }: VoiceHeartbeatTabProps) {
  const [search, setSearch] = useState("");

  const {
    voices,
    selectedVoice,
    ttsEnabled,
    setSelectedVoice,
    setTtsEnabled,
    previewVoice,
  } = useVoicePreferences({
    ttsBaseUrl: getApiBaseUrl() || (typeof window !== "undefined" ? window.location.origin : ""),
    preferencesEndpoint: buildApiUrl("/api/persona"),
    fetchFn: (url: string, options?: RequestInit) => fetchApi(url, options),
  });

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

  const handleHeartbeatChange = useCallback(
    (minutes: number) => {
      onUpdate({ heartbeat_interval_minutes: minutes });
    },
    [onUpdate],
  );

  return (
    <div className="space-y-8">
      {/* Voice Section */}
      <div className="space-y-4">
        <div>
          <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100 mb-1">
            Voice
          </h2>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Text-to-speech voice selection for persona responses.
          </p>
        </div>

        {/* TTS Toggle */}
        <div className="flex items-center justify-between max-w-md">
          <span className="text-sm text-slate-700 dark:text-slate-300">
            Text-to-speech
          </span>
          <button
            onClick={() => setTtsEnabled(!ttsEnabled)}
            className={cn(
              "relative w-10 h-5 rounded-full transition-colors duration-200",
              ttsEnabled ? "bg-amber-500" : "bg-slate-300 dark:bg-slate-600",
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
        <div className="relative max-w-md">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search voices..."
            className="w-full pl-8 pr-3 py-1.5 text-sm rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-amber-500/40"
          />
        </div>

        {/* Voice List */}
        <div className="max-h-[280px] overflow-y-auto rounded-lg border border-slate-200 dark:border-slate-700 max-w-md">
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
                    voice.id === selectedVoice && "bg-amber-50 dark:bg-amber-900/20",
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
      <div className="space-y-4">
        <div>
          <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100 mb-1">
            Heartbeat
          </h2>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Autonomous check-in schedule and instructions.
          </p>
        </div>

        <div className="flex items-center justify-between max-w-md">
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
        <p className="text-[10px] text-slate-400 max-w-md">
          How often {persona.name} runs autonomous system checks
        </p>

        {/* Heartbeat Instructions */}
        <DocumentSection
          label="Heartbeat Instructions"
          description="Custom instructions for autonomous heartbeat checks. Defines what to monitor and when to alert."
          value={persona.heartbeat_instructions || ""}
          placeholder="Describe what the persona should check during heartbeats..."
          onSave={(v) => onUpdate({ heartbeat_instructions: v })}
        />
      </div>
    </div>
  );
}
