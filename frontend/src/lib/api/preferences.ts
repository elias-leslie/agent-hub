/**
 * User preferences API
 */

import { getApiBaseUrl, fetchApi } from "../api-config";

const API_BASE = `${getApiBaseUrl()}/api`;

export interface UserPreferences {
  codex_auth_preference?: "oauth" | "api_key";
  claude_auth_preference?: "oauth" | "api_key";
}

export async function fetchUserPreferences(): Promise<UserPreferences> {
  const response = await fetchApi(`${API_BASE}/preferences`);
  if (!response.ok) {
    // Return defaults if not found
    if (response.status === 404) {
      return {
        codex_auth_preference: "oauth",
        claude_auth_preference: "oauth",
      };
    }
    throw new Error(`Preferences fetch failed: ${response.status}`);
  }
  return response.json();
}

export async function updateUserPreferences(
  prefs: Partial<UserPreferences>,
): Promise<UserPreferences> {
  const response = await fetchApi(`${API_BASE}/preferences`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(prefs),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Update preferences failed: ${response.status}`,
    );
  }
  return response.json();
}
