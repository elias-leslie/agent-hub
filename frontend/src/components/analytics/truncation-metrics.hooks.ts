import { useEffect, useState, useCallback } from "react";
import { getApiBaseUrl } from "@/lib/api-config";
import type { TruncationMetrics } from "./truncation-metrics.types";

export function useTruncationMetrics(days: number) {
  const [metrics, setMetrics] = useState<TruncationMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const fetchMetrics = useCallback(async () => {
    try {
      setLoading(true);
      const response = await fetch(
        `${getApiBaseUrl()}/api/analytics/truncations?days=${days}&group_by=model&include_recent=true&limit_recent=5`,
      );
      if (!response.ok) throw new Error("Failed to fetch metrics");
      const data = await response.json();
      setMetrics(data);
      setLastUpdated(new Date());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => {
    fetchMetrics();
    // Auto-refresh every 5 minutes
    const interval = setInterval(fetchMetrics, 5 * 60 * 1000);
    return () => clearInterval(interval);
  }, [days, fetchMetrics]);

  return { metrics, loading, error, lastUpdated, fetchMetrics };
}
