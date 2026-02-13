"use client";

import { useState, useEffect } from "react";
import { TierMatrixGrid, type QualityPreference } from "./tier-matrix-grid";
import { fetchApi, buildApiUrl } from "@/lib/api-config";

interface Preferences {
  model_tier_preference: QualityPreference;
}

export function PreferencesTab() {
  const [qualityPreference, setQualityPreference] =
    useState<QualityPreference>("standard");
  const [isLoading, setIsLoading] = useState(true);

  // Load preferences on mount
  useEffect(() => {
    const loadPreferences = async () => {
      try {
        const response = await fetchApi(buildApiUrl("/api/preferences"));
        if (response.ok) {
          const data: Preferences = await response.json();
          setQualityPreference(data.model_tier_preference);
        }
      } catch (error) {
        console.error("Failed to load preferences:", error);
      } finally {
        setIsLoading(false);
      }
    };

    loadPreferences();
  }, []);

  // Save preferences when tier changes
  const handlePreferenceChange = async (newPreference: QualityPreference) => {
    setQualityPreference(newPreference);

    try {
      await fetchApi(buildApiUrl("/api/preferences"), {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          model_tier_preference: newPreference,
        }),
      });
    } catch (error) {
      console.error("Failed to save preferences:", error);
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center p-8">
        <div className="text-sm text-slate-500 dark:text-slate-400">
          Loading preferences...
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Tier Matrix Grid - Main Feature */}
      <TierMatrixGrid
        preference={qualityPreference}
        onPreferenceChange={handlePreferenceChange}
      />

      {/* Other Preferences */}
      <div>
        <h3 className="text-sm font-medium text-slate-900 dark:text-slate-100 mb-3">
          Response Preferences
        </h3>
        <div className="space-y-3">
          <div className="flex items-center justify-between p-3 rounded-lg border border-slate-200 dark:border-slate-700">
            <div>
              <p className="text-sm font-medium text-slate-900 dark:text-slate-100">
                Response Verbosity
              </p>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                Control detail level in responses
              </p>
            </div>
            <select className="px-3 py-1.5 rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-sm">
              <option>Concise</option>
              <option>Balanced</option>
              <option>Detailed</option>
            </select>
          </div>
          <div className="flex items-center justify-between p-3 rounded-lg border border-slate-200 dark:border-slate-700">
            <div>
              <p className="text-sm font-medium text-slate-900 dark:text-slate-100">
                Default Model
              </p>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                Preferred model for new sessions
              </p>
            </div>
            <select className="px-3 py-1.5 rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-sm">
              <option>claude-sonnet-4-5</option>
              <option>claude-haiku-4-5</option>
              <option>gemini-2.0-flash</option>
            </select>
          </div>
        </div>
      </div>
      <div className="pt-4 border-t border-slate-200 dark:border-slate-700">
        <p className="text-xs text-slate-500 dark:text-slate-400">
          Preferences are saved locally and applied to future sessions.
        </p>
      </div>
    </div>
  );
}
