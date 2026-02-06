/**
 * Credentials API
 */

import { getApiBaseUrl, fetchApi } from "../api-config";

const API_BASE = `${getApiBaseUrl()}/api`;

export interface Credential {
  id: number;
  provider: string;
  credential_type: string;
  value_masked: string;
  created_at: string;
  updated_at: string;
}

export interface CredentialListResponse {
  credentials: Credential[];
  total: number;
}

export interface CredentialCreate {
  provider: string;
  credential_type: string;
  value: string;
}

export async function fetchCredentials(
  provider?: string,
): Promise<CredentialListResponse> {
  const url = provider
    ? `${API_BASE}/credentials?provider=${provider}`
    : `${API_BASE}/credentials`;
  const response = await fetchApi(url);
  if (!response.ok) {
    throw new Error(`Credentials fetch failed: ${response.status}`);
  }
  return response.json();
}

export async function createCredential(
  data: CredentialCreate,
): Promise<Credential> {
  const response = await fetchApi(`${API_BASE}/credentials`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Create credential failed: ${response.status}`,
    );
  }
  return response.json();
}

export async function updateCredential(
  id: number,
  value: string,
): Promise<Credential> {
  const response = await fetchApi(`${API_BASE}/credentials/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ value }),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Update credential failed: ${response.status}`,
    );
  }
  return response.json();
}

export async function deleteCredential(id: number): Promise<void> {
  const response = await fetchApi(`${API_BASE}/credentials/${id}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    throw new Error(`Delete credential failed: ${response.status}`);
  }
}
