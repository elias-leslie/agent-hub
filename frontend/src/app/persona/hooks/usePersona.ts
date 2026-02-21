import { useState, useEffect, useCallback, useRef } from "react";
import { fetchApi, buildApiUrl } from "@/lib/api-config";
import type { Persona, PersonaUpdate } from "@/types/persona";

interface UsePersonaReturn {
  persona: Persona | null;
  loading: boolean;
  error: string | null;
  updatePersona: (fields: PersonaUpdate) => Promise<void>;
}

export function usePersona(): UsePersonaReturn {
  const [persona, setPersona] = useState<Persona | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function fetchPersona() {
      try {
        const res = await fetchApi(buildApiUrl("/api/persona"));
        if (!res.ok) throw new Error(`Failed to fetch persona: ${res.status}`);
        const data = await res.json();
        if (!cancelled) setPersona(data);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load persona");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    fetchPersona();
    return () => { cancelled = true; };
  }, []);

  const updatePersona = useCallback(async (fields: PersonaUpdate) => {
    // Optimistic update
    setPersona((prev) => prev ? { ...prev, ...fields } : prev);

    // Debounced save
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(async () => {
      try {
        const res = await fetchApi(buildApiUrl("/api/persona"), {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(fields),
        });
        if (!res.ok) throw new Error(`Failed to update persona: ${res.status}`);
        const updated = await res.json();
        setPersona(updated);
      } catch (err) {
        console.error("Failed to save persona:", err);
      }
    }, 500);
  }, []);

  return { persona, loading, error, updatePersona };
}
