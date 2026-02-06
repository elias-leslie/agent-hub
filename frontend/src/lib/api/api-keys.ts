/**
 * API Keys management API
 */

import { getApiBaseUrl, fetchApi } from "../api-config";

const API_BASE = `${getApiBaseUrl()}/api`;

export interface APIKey {
  id: number;
  key_prefix: string;
  name: string | null;
  project_id: string;
  rate_limit_rpm: number;
  rate_limit_tpm: number;
  is_active: boolean;
  last_used_at: string | null;
  created_at: string;
  expires_at: string | null;
}

export interface APIKeyCreate {
  name?: string;
  project_id?: string;
  rate_limit_rpm?: number;
  rate_limit_tpm?: number;
  expires_in_days?: number;
}

export interface APIKeyCreateResponse extends APIKey {
  key: string; // Full key, shown only once
}

export interface APIKeyListResponse {
  keys: APIKey[];
  total: number;
}

export async function fetchAPIKeys(params?: {
  project_id?: string;
  include_revoked?: boolean;
}): Promise<APIKeyListResponse> {
  const searchParams = new URLSearchParams();
  if (params?.project_id) searchParams.set("project_id", params.project_id);
  if (params?.include_revoked) searchParams.set("include_revoked", "true");

  const url = searchParams.toString()
    ? `${API_BASE}/api-keys?${searchParams}`
    : `${API_BASE}/api-keys`;

  const response = await fetchApi(url);
  if (!response.ok) {
    throw new Error(`API keys fetch failed: ${response.status}`);
  }
  return response.json();
}

export async function createAPIKey(
  data: APIKeyCreate,
): Promise<APIKeyCreateResponse> {
  const response = await fetchApi(`${API_BASE}/api-keys`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Create API key failed: ${response.status}`,
    );
  }
  return response.json();
}

export async function updateAPIKey(
  id: number,
  data: { name?: string; rate_limit_rpm?: number; rate_limit_tpm?: number },
): Promise<APIKey> {
  const response = await fetchApi(`${API_BASE}/api-keys/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Update API key failed: ${response.status}`,
    );
  }
  return response.json();
}

export async function revokeAPIKey(id: number): Promise<APIKey> {
  const response = await fetchApi(`${API_BASE}/api-keys/${id}/revoke`, {
    method: "POST",
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Revoke API key failed: ${response.status}`,
    );
  }
  return response.json();
}

export async function deleteAPIKey(id: number): Promise<void> {
  const response = await fetchApi(`${API_BASE}/api-keys/${id}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    throw new Error(`Delete API key failed: ${response.status}`);
  }
}
