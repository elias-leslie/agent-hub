"use client";

import { useState, useRef, useEffect, useMemo } from "react";
import { Volume2, VolumeX, Play, Search, Check } from "lucide-react";
import { cn } from "../lib/utils";
import { useVoicePreferences, type VoiceOption } from "../hooks/use-voice-preferences";

interface SpeakerButtonProps {
  ttsBaseUrl: string;
  preferencesEndpoint?: string;
  fetchFn?: (url: string, options?: RequestInit) => Promise<Response>;
  isSpeaking?: boolean;
  onStopSpeaking?: () => void;
  onVoiceChange?: (voiceId: string) => void;
  onEnabledChange?: (enabled: boolean) => void;
}

export function SpeakerButton({
  ttsBaseUrl,
  preferencesEndpoint,
  fetchFn,
  isSpeaking = false,
  onStopSpeaking,
  onVoiceChange,
  onEnabledChange,
}: SpeakerButtonProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [search, setSearch] = useState("");
  const popoverRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  const {
    voices,
    selectedVoice,
    ttsEnabled,
    setSelectedVoice,
    setTtsEnabled,
    previewVoice,
  } = useVoicePreferences({ ttsBaseUrl, preferencesEndpoint, fetchFn });

  // Close on outside click
  useEffect(() => {
    if (!isOpen) return;
    function handleClick(e: MouseEvent) {
      if (
        popoverRef.current &&
        !popoverRef.current.contains(e.target as Node) &&
        buttonRef.current &&
        !buttonRef.current.contains(e.target as Node)
      ) {
        setIsOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [isOpen]);

  // Notify parent of changes
  useEffect(() => { onVoiceChange?.(selectedVoice); }, [selectedVoice, onVoiceChange]);
  useEffect(() => { onEnabledChange?.(ttsEnabled); }, [ttsEnabled, onEnabledChange]);

  const handleButtonClick = () => {
    if (isSpeaking) {
      onStopSpeaking?.();
    } else {
      setIsOpen((prev) => !prev);
    }
  };

  const handleToggle = () => {
    setTtsEnabled(!ttsEnabled);
  };

  const handleSelectVoice = (voiceId: string) => {
    setSelectedVoice(voiceId);
  };

  const handlePreview = (e: React.MouseEvent, voiceId: string) => {
    e.stopPropagation();
    previewVoice(voiceId);
  };

  // Group and filter voices
  const filteredVoices = useMemo(() => {
    const lowerSearch = search.toLowerCase();
    return voices.filter(
      (v) =>
        v.name.toLowerCase().includes(lowerSearch) ||
        v.locale.toLowerCase().includes(lowerSearch) ||
        v.personalities.some((p) => p.toLowerCase().includes(lowerSearch))
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
    <div className="relative">
      <button
        ref={buttonRef}
        data-testid="speaker-button"
        onClick={handleButtonClick}
        aria-label={isSpeaking ? "Stop speaking" : ttsEnabled ? "TTS enabled" : "TTS disabled"}
        title={isSpeaking ? "Stop speaking" : "Voice settings"}
        className={cn(
          "flex items-center justify-center w-10 h-10 rounded-xl",
          "transition-colors duration-150",
          isSpeaking
            ? "bg-purple-500 hover:bg-purple-600 text-white cursor-pointer animate-pulse"
            : ttsEnabled
              ? "bg-purple-100 hover:bg-purple-200 dark:bg-purple-900/30 dark:hover:bg-purple-900/50 text-purple-600 dark:text-purple-400 cursor-pointer"
              : "bg-gray-200 hover:bg-gray-300 dark:bg-gray-700 dark:hover:bg-gray-600 text-gray-500 dark:text-gray-400 cursor-pointer"
        )}
      >
        {isSpeaking || ttsEnabled ? (
          <Volume2 className="w-5 h-5" />
        ) : (
          <VolumeX className="w-5 h-5" />
        )}
      </button>

      {isOpen && (
        <div
          ref={popoverRef}
          className={cn(
            "absolute bottom-full mb-2 right-0 w-80",
            "rounded-xl border border-gray-200 dark:border-gray-700",
            "bg-white dark:bg-gray-800 shadow-xl",
            "z-50 overflow-hidden"
          )}
        >
          {/* Toggle */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 dark:border-gray-700">
            <span className="text-sm font-medium text-gray-900 dark:text-gray-100">
              Auto-speak responses
            </span>
            <button
              onClick={handleToggle}
              className={cn(
                "relative w-10 h-5 rounded-full transition-colors duration-200",
                ttsEnabled
                  ? "bg-purple-500"
                  : "bg-gray-300 dark:bg-gray-600"
              )}
            >
              <span
                className={cn(
                  "absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform duration-200",
                  ttsEnabled && "translate-x-5"
                )}
              />
            </button>
          </div>

          {/* Search */}
          <div className="px-3 py-2 border-b border-gray-200 dark:border-gray-700">
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search voices..."
                className="w-full pl-8 pr-3 py-1.5 text-sm rounded-lg border border-gray-200 dark:border-gray-600 bg-gray-50 dark:bg-gray-900 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-purple-500"
              />
            </div>
          </div>

          {/* Voice list */}
          <div className="max-h-[300px] overflow-y-auto">
            {Object.entries(grouped).map(([gender, groupVoices]) => (
              <div key={gender}>
                <div className="px-4 py-1.5 text-xs font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-900/50 sticky top-0">
                  {gender}
                </div>
                {groupVoices.map((voice) => (
                  <button
                    key={voice.id}
                    onClick={() => handleSelectVoice(voice.id)}
                    className={cn(
                      "w-full flex items-center gap-2 px-4 py-2 text-left hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors",
                      voice.id === selectedVoice && "bg-purple-50 dark:bg-purple-900/20"
                    )}
                  >
                    {/* Preview play */}
                    <button
                      onClick={(e) => handlePreview(e, voice.id)}
                      className="flex-shrink-0 p-1 rounded-md hover:bg-gray-200 dark:hover:bg-gray-600 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
                      title="Preview voice"
                    >
                      <Play className="w-3 h-3" />
                    </button>

                    {/* Voice info */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span className="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">
                          {voice.name}
                        </span>
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-400 flex-shrink-0">
                          {voice.locale}
                        </span>
                      </div>
                      {voice.personalities.length > 0 && (
                        <div className="flex gap-1 mt-0.5">
                          {voice.personalities.slice(0, 3).map((p) => (
                            <span
                              key={p}
                              className="text-[10px] text-gray-400 dark:text-gray-500"
                            >
                              {p}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>

                    {/* Selected check */}
                    {voice.id === selectedVoice && (
                      <Check className="w-4 h-4 text-purple-500 flex-shrink-0" />
                    )}
                  </button>
                ))}
              </div>
            ))}
            {filteredVoices.length === 0 && (
              <div className="px-4 py-6 text-center text-sm text-gray-500 dark:text-gray-400">
                No voices found
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
