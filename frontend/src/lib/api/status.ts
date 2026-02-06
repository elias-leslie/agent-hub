/**
 * Status and provider health API
 */

import { getApiBaseUrl, fetchApi } from "../api-config";

const API_BASE = `${getApiBaseUrl()}/api`;

export interface ProviderHealthDetails {
  state: "healthy" | "degraded" | "unavailable" | "unknown";
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
  health: ProviderHealthDetails | null;
}

export interface StatusResponse {
  status: "healthy" | "degraded";
  service: string;
  database: string;
  providers: ProviderStatus[];
  uptime_seconds: number;
}

export async function fetchStatus(): Promise<StatusResponse> {
  const response = await fetchApi(`${API_BASE}/status`);
  if (!response.ok) {
    throw new Error(`Status fetch failed: ${response.status}`);
  }
  return response.json();
}
