"use client";

import { useState, useEffect } from "react";
import { X, Key, Sliders } from "lucide-react";
import { cn } from "@/lib/utils";
import { PreferencesTab } from "./settings/PreferencesTab";
import { ProvidersTab } from "./settings/ProvidersTab";

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
    <div className="fixed inset-0 z-50 flex items-stretch justify-stretch p-4">
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={onClose}
      />
      <div className="relative flex flex-col w-full rounded-xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 dark:border-slate-800 shrink-0">
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
        <div className="flex items-center gap-1 px-6 pt-4 border-b border-slate-200 dark:border-slate-800 shrink-0">
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

        {/* Content — fills remaining space */}
        <div className="flex-1 overflow-y-auto overflow-x-hidden p-6">
          {activeTab === "preferences" && <PreferencesTab />}
          {activeTab === "providers" && <ProvidersTab />}
        </div>
      </div>
    </div>
  );
}
