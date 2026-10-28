"use client";

import { useCallback, useEffect, useMemo, useRef } from "react";
import { useVoice } from "@agent-hub/passport-client";
import type { ChatVoice } from "../types/voice";
import { useVoicePreferences, type VoicePreferencesStore } from "./use-voice-preferences";

export interface UseChatVoiceOptions {
  /** The voice socket (`/api/voice/ws?...`). Without it there is no mic button. */
  voiceWsUrl?: string;
  /** The voice service for speech. Without it there is no speaker button. */
  ttsBaseUrl?: string;
  /** Where the speaker's voice and on/off choice are kept (see `createHttpPreferencesStore`). */
  preferences?: VoicePreferencesStore;
  /** The host's `fetch` for the voice service. */
  fetchFn?: (url: string, init?: RequestInit) => Promise<Response>;
}

/**
 * Voice for the chat, built on `@agent-hub/passport-client`. Pass the result to `<ChatPanel voice={...}>`. This is
 * the only part of the package that needs passport-client, so hosts without it import `@agent-hub/chat-ui` alone.
 */
export function useChatVoice({ voiceWsUrl, ttsBaseUrl, preferences, fetchFn }: UseChatVoiceOptions): ChatVoice {
  const transcriptHandlerRef = useRef<((text: string) => void) | null>(null);
  const setTranscriptHandler = useCallback((handler: ((text: string) => void) | null) => {
    transcriptHandlerRef.current = handler;
  }, []);
  const onTranscript = useCallback((text: string) => transcriptHandlerRef.current?.(text), []);

  const { isRecording, isConnected, isSpeaking, connect, startRecording, stopRecording, speakText, stopSpeaking } =
    useVoice({ onTranscript, ttsBaseUrl });

  useEffect(() => {
    if (voiceWsUrl && !isConnected) {
      connect(voiceWsUrl);
    }
  }, [voiceWsUrl, isConnected, connect]);

  const { selectedVoice, ttsEnabled, setTtsEnabled } = useVoicePreferences({
    ttsBaseUrl,
    preferences: ttsBaseUrl ? preferences : undefined,
    fetchFn,
  });

  return useMemo(
    () => ({
      micAvailable: Boolean(voiceWsUrl),
      speakerAvailable: Boolean(ttsBaseUrl),
      isRecording,
      isSpeaking,
      ttsEnabled,
      selectedVoice,
      startRecording,
      stopRecording,
      speakText,
      stopSpeaking,
      setTtsEnabled,
      setTranscriptHandler,
    }),
    [voiceWsUrl, ttsBaseUrl, isRecording, isSpeaking, ttsEnabled, selectedVoice, startRecording, stopRecording, speakText, stopSpeaking, setTtsEnabled, setTranscriptHandler],
  );
}
