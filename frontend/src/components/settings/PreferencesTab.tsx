"use client";

import { useState, useEffect } from "react";
import { TierMatrixGrid, type QualityPreference } from "./tier-matrix-grid";
import { fetchApi, buildApiUrl } from "@/lib/api-config";
import { getModels, type CatalogModel } from "@/lib/models";

interface Preferences {
  model_tier_preference: QualityPreference;
  heartbeat_interval_minutes: number;
}

export function PreferencesTab() {
  const [qualityPreference, setQualityPreference] =
    useState<QualityPreference>("standard");
  const [heartbeatInterval, setHeartbeatInterval] = useState(60);
  const [isLoading, setIsLoading] = useState(true);
  const [availableModels, setAvailableModels] = useState<CatalogModel[]>([]);

  // Load preferences and models on mount
  useEffect(() => {
    const loadData = async () => {
      try {
        const [prefsResponse, models] = await Promise.all([
          fetchApi(buildApiUrl("/api/preferences")),
          getModels(),
        ]);
        if (prefsResponse.ok) {
          const data: Preferences = await prefsResponse.json();
          setQualityPreference(data.model_tier_preference);
          if (data.heartbeat_interval_minutes !== undefined) {
            setHeartbeatInterval(data.heartbeat_interval_minutes);
          }
        }
        setAvailableModels(models);
      } catch (error) {
        console.error("Failed to load preferences:", error);
      } finally {
        setIsLoading(false);
      }
    };

    loadData();
  }, []);

  // Save preferences when tier changes
  const handlePreferenceChange = async (newPreference: QualityPreference) => {
    setQualityPreference(newPreference);

    try {
      await fetchApi(buildApiUrl("/api/preferences"), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model_tier_preference: newPreference }),
      });
    } catch (error) {
      console.error("Failed to save preferences:", error);
    }
  };

  const handleHeartbeatChange = async (minutes: number) => {
    setHeartbeatInterval(minutes);

    try {
      await fetchApi(buildApiUrl("/api/preferences"), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ heartbeat_interval_minutes: minutes }),
      });
    } catch (error) {
      console.error("Failed to save heartbeat preference:", error);
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
              {availableModels.map((m) => (
                <option key={m.id} value={m.id}>{m.name}</option>
              ))}
            </select>
          </div>
          <div className="flex items-center justify-between p-3 rounded-lg border border-slate-200 dark:border-slate-700">
            <div>
              <p className="text-sm font-medium text-slate-900 dark:text-slate-100">
                Heartbeat Interval
              </p>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                How often Johnny checks in with updates
              </p>
            </div>
            <select
              value={heartbeatInterval}
              onChange={(e) => handleHeartbeatChange(Number(e.target.value))}
              className="px-3 py-1.5 rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-sm"
            >
              <option value={15}>15 min</option>
              <option value={30}>30 min</option>
              <option value={60}>1 hour</option>
              <option value={120}>2 hours</option>
              <option value={240}>4 hours</option>
              <option value={0}>Off</option>
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
