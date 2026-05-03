"use client";

import { useEffect } from "react";
import { Volume2, VolumeX } from "lucide-react";
import { cn } from "../lib/utils";
import { useVoicePreferences } from "../hooks/use-voice-preferences";

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
  const {
    selectedVoice,
    ttsEnabled,
    setTtsEnabled,
  } = useVoicePreferences({ ttsBaseUrl, preferencesEndpoint, fetchFn });

  // Notify parent of changes
  useEffect(() => { onVoiceChange?.(selectedVoice); }, [selectedVoice, onVoiceChange]);
  useEffect(() => { onEnabledChange?.(ttsEnabled); }, [ttsEnabled, onEnabledChange]);

  const handleClick = () => {
    if (isSpeaking) {
      onStopSpeaking?.();
    } else {
      setTtsEnabled(!ttsEnabled);
    }
  };

  return (
    <button
      data-testid="speaker-button"
      onClick={handleClick}
      aria-label={isSpeaking ? "Stop speaking" : ttsEnabled ? "TTS enabled" : "TTS disabled"}
      title={isSpeaking ? "Stop speaking" : ttsEnabled ? "Disable TTS" : "Enable TTS"}
      className={cn(
        "flex items-center justify-center w-10 h-10 rounded-xl",
        "transition-colors duration-150",
        isSpeaking
          ? "bg-destructive hover:bg-destructive/90 text-white cursor-pointer animate-pulse"
          : ttsEnabled
            ? "bg-primary text-primary-foreground hover:bg-primary/90 cursor-pointer"
            : "bg-secondary text-secondary-foreground hover:bg-accent hover:text-accent-foreground cursor-pointer"
      )}
    >
      {isSpeaking || ttsEnabled ? (
        <Volume2 className="w-5 h-5" />
      ) : (
        <VolumeX className="w-5 h-5" />
      )}
    </button>
  );
}
