"use client";

import { useCallback, useEffect, useState } from "react";

/**
 * Provider health details from the /status endpoint.
 */
export interface ProviderHealth {
  state: "healthy" | "degraded" | "down" | "unknown";
  latency_ms: number;
  error_rate: number;
  availability: number;
  consecutive_failures: number;
  last_check: number | null;
  last_success: number | null;
  last_error: string | null;
}

export interface ProviderStatus {
  name: string;
  available: boolean;
  configured: boolean;
  error: string | null;
  health: ProviderHealth | null;
}

export interface StatusResponse {
  status: "healthy" | "degraded";
  service: string;
  database: string;
  providers: ProviderStatus[];
  uptime_seconds: number;
}

export interface QueueInfo {
  position: number | null;
  estimatedWaitMs: number | null;
}

export interface ProviderStatusState {
  status: StatusResponse | null;
  queueInfo: QueueInfo | null;
  isLoading: boolean;
  error: string | null;
  isDegraded: boolean;
  availableProviders: string[];
  unavailableProviders: string[];
  recoveryEta: number | null;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8003";

/**
 * Hook to monitor provider status and degraded mode.
 *
 * Polls the /status endpoint periodically and tracks when providers
 * are degraded or down.
 */
export function useProviderStatus(
  pollIntervalMs: number = 30000
): ProviderStatusState & {
  refresh: () => Promise<void>;
} {
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [queueInfo, setQueueInfo] = useState<QueueInfo | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchStatus = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/status`);
      if (!response.ok) {
        throw new Error(`Status check failed: ${response.status}`);
      }
      const data: StatusResponse = await response.json();
      setStatus(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch status");
    } finally {
      setIsLoading(false);
    }
  }, []);

  const refresh = useCallback(async () => {
    setIsLoading(true);
    await fetchStatus();
  }, [fetchStatus]);

  // Initial fetch and polling
  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, pollIntervalMs);
    return () => clearInterval(interval);
  }, [fetchStatus, pollIntervalMs]);

  // Compute derived state
  const availableProviders =
    status?.providers
      .filter((p) => p.available)
      .map((p) => p.name) ?? [];

  const unavailableProviders =
    status?.providers
      .filter((p) => p.configured && !p.available)
      .map((p) => p.name) ?? [];

  const isDegraded =
    status?.status === "degraded" || unavailableProviders.length > 0;

  // Estimate recovery time based on last error time and typical recovery
  const recoveryEta = (() => {
    if (!isDegraded || !status) return null;

    // Find the most recent failure
    const downProviders = status.providers.filter(
      (p) => p.health?.state === "down" || p.health?.state === "degraded"
    );

    if (downProviders.length === 0) return null;

    // Estimate based on typical recovery time (2 minutes) minus time since failure
    const typicalRecoveryMs = 120000;
    const now = Date.now() / 1000;

    for (const provider of downProviders) {
      if (provider.health?.last_check) {
        const timeSinceCheck = now - provider.health.last_check;
        const remaining = Math.max(0, typicalRecoveryMs / 1000 - timeSinceCheck);
        if (remaining > 0) {
          return remaining * 1000;
        }
      }
    }

    return null;
  })();

  return {
    status,
    queueInfo,
    isLoading,
    error,
    isDegraded,
    availableProviders,
    unavailableProviders,
    recoveryEta,
    refresh,
  };
}

/**
 * Update queue position (called when request is queued).
 */
export function updateQueueInfo(
  setQueueInfo: React.Dispatch<React.SetStateAction<QueueInfo | null>>,
  position: number | null,
  estimatedWaitMs: number | null
) {
  setQueueInfo({ position, estimatedWaitMs });
}
