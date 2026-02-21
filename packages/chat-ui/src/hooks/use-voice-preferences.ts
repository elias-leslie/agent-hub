"use client";

import { useState, useEffect, useCallback, useRef } from "react";

export interface VoiceOption {
  id: string;
  name: string;
  gender: string;
  locale: string;
  personalities: string[];
}

interface UseVoicePreferencesOptions {
  ttsBaseUrl: string;
  preferencesEndpoint?: string;
  fetchFn?: (url: string, options?: RequestInit) => Promise<Response>;
}

export function useVoicePreferences({
  ttsBaseUrl,
  preferencesEndpoint,
  fetchFn = fetch,
}: UseVoicePreferencesOptions) {
  const [voices, setVoices] = useState<VoiceOption[]>([]);
  const [selectedVoice, setSelectedVoice] = useState("en-US-AriaNeural");
  const [ttsEnabled, setTtsEnabled] = useState(false);
  const [loading, setLoading] = useState(true);
  const previewAudioRef = useRef<AudioBufferSourceNode | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Fetch voice list
  useEffect(() => {
    let cancelled = false;
    async function fetchVoices() {
      try {
        const res = await fetch(`${ttsBaseUrl}/api/voice/voices?locale=en`);
        if (!res.ok) return;
        const data = await res.json();
        if (!cancelled) setVoices(data.voices || []);
      } catch {
        // Non-critical — voice list may be unavailable
      }
    }
    fetchVoices();
    return () => { cancelled = true; };
  }, [ttsBaseUrl]);

  // Fetch preferences
  useEffect(() => {
    if (!preferencesEndpoint) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    async function fetchPrefs() {
      try {
        const res = await fetchFn(preferencesEndpoint!);
        if (!res.ok) return;
        const data = await res.json();
        if (!cancelled) {
          if (data.tts_voice) setSelectedVoice(data.tts_voice);
          if (typeof data.tts_enabled === "boolean") setTtsEnabled(data.tts_enabled);
        }
      } catch {
        // Non-critical
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    fetchPrefs();
    return () => { cancelled = true; };
  }, [preferencesEndpoint, fetchFn]);

  // Debounced save to preferences
  const savePreferences = useCallback(
    (voice: string, enabled: boolean) => {
      if (!preferencesEndpoint) return;
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
      saveTimerRef.current = setTimeout(async () => {
        try {
          await fetchFn(preferencesEndpoint, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ tts_voice: voice, tts_enabled: enabled }),
          });
        } catch {
          // Silent — preference save is best-effort
        }
      }, 500);
    },
    [preferencesEndpoint, fetchFn]
  );

  const updateSelectedVoice = useCallback(
    (voiceId: string) => {
      setSelectedVoice(voiceId);
      setTtsEnabled((prev) => {
        savePreferences(voiceId, prev);
        return prev;
      });
    },
    [savePreferences]
  );

  const updateTtsEnabled = useCallback(
    (enabled: boolean) => {
      setTtsEnabled(enabled);
      setSelectedVoice((prev) => {
        savePreferences(prev, enabled);
        return prev;
      });
    },
    [savePreferences]
  );

  const previewVoice = useCallback(
    async (voiceId: string) => {
      // Cancel previous preview
      if (previewAudioRef.current) {
        try { previewAudioRef.current.stop(); } catch { /* already stopped */ }
        previewAudioRef.current = null;
      }

      try {
        const res = await fetch(`${ttsBaseUrl}/api/voice/tts`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: "Hello! This is how I sound.", voice: voiceId }),
        });
        if (!res.ok) return;

        const audioData = await res.arrayBuffer();
        if (!audioCtxRef.current) {
          audioCtxRef.current = new AudioContext();
        }
        const ctx = audioCtxRef.current;
        const buffer = await ctx.decodeAudioData(audioData);
        const source = ctx.createBufferSource();
        source.buffer = buffer;
        source.connect(ctx.destination);
        previewAudioRef.current = source;
        source.onended = () => { previewAudioRef.current = null; };
        source.start(0);
      } catch {
        // Preview failed — non-critical
      }
    },
    [ttsBaseUrl]
  );

  return {
    voices,
    selectedVoice,
    ttsEnabled,
    loading,
    setSelectedVoice: updateSelectedVoice,
    setTtsEnabled: updateTtsEnabled,
    previewVoice,
  };
}
