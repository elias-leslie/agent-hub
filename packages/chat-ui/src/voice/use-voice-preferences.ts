"use client";

import { useState, useEffect, useCallback, useRef } from "react";

export interface VoiceOption {
  id: string;
  name: string;
  gender: string;
  locale: string;
  personalities: string[];
}

export interface VoicePreferences {
  voice?: string;
  enabled?: boolean;
}

/** Where the host keeps the speaker's voice and on/off choice. The chat does not know how or where. */
export interface VoicePreferencesStore {
  load(): Promise<VoicePreferences | null>;
  save(preferences: { voice: string; enabled: boolean }): Promise<void>;
}

type FetchLike = (url: string, init?: RequestInit) => Promise<Response>;

/**
 * A store over a JSON endpoint: GET returns `{ tts_voice, tts_enabled }`, PUT takes the same. `fetch` is the host's
 * (for example one that adds auth headers).
 */
export function createHttpPreferencesStore(endpoint: string, fetchFn: FetchLike = (url, init) => fetch(url, init)): VoicePreferencesStore {
  return {
    async load() {
      const res = await fetchFn(endpoint);
      if (!res.ok) return null;
      const data = await res.json();
      return {
        voice: typeof data.tts_voice === "string" && data.tts_voice ? data.tts_voice : undefined,
        enabled: typeof data.tts_enabled === "boolean" ? data.tts_enabled : undefined,
      };
    },
    async save({ voice, enabled }) {
      await fetchFn(endpoint, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tts_voice: voice, tts_enabled: enabled }),
      });
    },
  };
}

interface UseVoicePreferencesOptions {
  /** The voice service (it lists voices and speaks previews). Undefined: no voice service, nothing is fetched. */
  ttsBaseUrl: string | undefined;
  /** Where the choice is kept. Without it the choice lasts for the page only. */
  preferences?: VoicePreferencesStore;
  /** For the voice service's own calls. Defaults to the platform `fetch`. */
  fetchFn?: FetchLike;
}

export function useVoicePreferences({
  ttsBaseUrl,
  preferences,
  fetchFn = (url, init) => fetch(url, init),
}: UseVoicePreferencesOptions) {
  const [voices, setVoices] = useState<VoiceOption[]>([]);
  const [selectedVoice, setSelectedVoice] = useState("en-US-AriaNeural");
  const [ttsEnabled, setTtsEnabled] = useState(false);
  const [loading, setLoading] = useState(true);
  const previewAudioRef = useRef<AudioBufferSourceNode | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const fetchRef = useRef(fetchFn);
  fetchRef.current = fetchFn;

  // Fetch voice list
  useEffect(() => {
    if (ttsBaseUrl === undefined) return;
    let cancelled = false;
    async function fetchVoices() {
      try {
        const res = await fetchRef.current(`${ttsBaseUrl}/api/voice/voices?locale=en`);
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

  // Load the saved choice
  useEffect(() => {
    if (!preferences) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    async function loadPrefs() {
      try {
        const saved = await preferences!.load();
        if (cancelled || !saved) return;
        if (saved.voice) setSelectedVoice(saved.voice);
        if (typeof saved.enabled === "boolean") setTtsEnabled(saved.enabled);
      } catch {
        // Non-critical
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    loadPrefs();
    return () => { cancelled = true; };
  }, [preferences]);

  // Debounced save
  const savePreferences = useCallback(
    (voice: string, enabled: boolean) => {
      if (!preferences) return;
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
      saveTimerRef.current = setTimeout(async () => {
        try {
          await preferences.save({ voice, enabled });
        } catch {
          // Silent — preference save is best-effort
        }
      }, 500);
    },
    [preferences]
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
      if (ttsBaseUrl === undefined) return;
      // Cancel previous preview
      if (previewAudioRef.current) {
        try { previewAudioRef.current.stop(); } catch { /* already stopped */ }
        previewAudioRef.current = null;
      }

      try {
        const res = await fetchRef.current(`${ttsBaseUrl}/api/voice/tts`, {
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
