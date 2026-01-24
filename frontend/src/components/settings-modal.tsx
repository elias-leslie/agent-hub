"use client";

import { useState, useEffect } from "react";
import { X, Key, Sliders } from "lucide-react";
import { cn } from "@/lib/utils";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  fetchCredentials,
  type Credential,
} from "@/lib/api";

const TABS = [
  { id: "preferences", label: "Preferences", icon: Sliders },
  { id: "providers", label: "LLM Providers", icon: Key },
] as const;

type TabId = (typeof TABS)[number]["id"];

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export function SettingsModal({ isOpen, onClose }: SettingsModalProps) {
  const [activeTab, setActiveTab] = useState<TabId>("preferences");

  useEffect(() => {
    if (!isOpen) setActiveTab("preferences");
  }, [isOpen]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={onClose}
      />
      <div className="relative w-full max-w-3xl mx-4 rounded-xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 dark:border-slate-800">
          <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
            Settings
          </h2>
          <button
            onClick={onClose}
            className="p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-500 dark:text-slate-400 transition-colors"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Tabs */}
        <div className="flex items-center gap-1 px-6 pt-4 border-b border-slate-200 dark:border-slate-800">
          {TABS.map((tab) => {
            const Icon = tab.icon;
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={cn(
                  "flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors",
                  isActive
                    ? "border-amber-500 text-amber-600 dark:text-amber-400"
                    : "border-transparent text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-300"
                )}
              >
                <Icon className="h-4 w-4" />
                {tab.label}
              </button>
            );
          })}
        </div>

        {/* Content */}
        <div className="p-6 max-h-[60vh] overflow-y-auto">
          {activeTab === "preferences" && <PreferencesTab />}
          {activeTab === "providers" && <ProvidersTab />}
        </div>
      </div>
    </div>
  );
}

function PreferencesTab() {
  return (
    <div className="space-y-6">
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

function ProvidersTab() {
  const { data, isLoading } = useQuery({
    queryKey: ["credentials"],
    queryFn: () => fetchCredentials(),
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-slate-900 dark:text-slate-100">
          Provider Credentials
        </h3>
        <a
          href="/access-control"
          className="px-3 py-1.5 rounded-lg text-sm font-medium bg-amber-500 hover:bg-amber-600 text-white transition-colors"
        >
          Manage Credentials →
        </a>
      </div>

      {isLoading && (
        <div className="text-center py-8 text-slate-500">
          Loading credentials...
        </div>
      )}

      {data && data.credentials.length === 0 && (
        <div className="text-center py-8 text-slate-500 dark:text-slate-400">
          <Key className="h-12 w-12 mx-auto mb-2 opacity-30" />
          <p className="text-sm">No credentials configured</p>
        </div>
      )}

      {data && data.credentials.length > 0 && (
        <div className="space-y-2">
          {data.credentials.map((credential) => (
            <div
              key={credential.id}
              className="flex items-center justify-between p-3 rounded-lg border border-slate-200 dark:border-slate-700"
            >
              <div>
                <p className="text-sm font-medium text-slate-900 dark:text-slate-100 capitalize">
                  {credential.provider}
                </p>
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  {credential.credential_type.replace("_", " ")} •{" "}
                  {new Date(credential.updated_at).toLocaleDateString()}
                </p>
              </div>
              <code className="text-xs font-mono text-slate-500">
                {credential.value_masked}
              </code>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
