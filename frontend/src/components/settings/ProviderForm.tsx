"use client";

import { useState } from "react";
import { Eye, EyeOff, Check, Loader2 } from "lucide-react";

interface ProviderFormProps {
  providerName: string;
  onSave: (value: string) => void;
  onCancel: () => void;
  isSaving: boolean;
  error: string | null;
}

export function ProviderForm({
  providerName,
  onSave,
  onCancel,
  isSaving,
  error,
}: ProviderFormProps) {
  const [keyValue, setKeyValue] = useState("");
  const [showPassword, setShowPassword] = useState(false);

  function handleSave() {
    if (!keyValue.trim()) return;
    onSave(keyValue.trim());
  }

  return (
    <div className="mt-3 pt-3 border-t border-slate-200 dark:border-slate-700">
      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <input
            type={showPassword ? "text" : "password"}
            value={keyValue}
            onChange={(e) => setKeyValue(e.target.value)}
            placeholder={`Enter ${providerName} API key`}
            className="w-full px-3 py-2 pr-9 rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-amber-500/50 focus:border-amber-500"
            autoFocus
            onKeyDown={(e) => {
              if (e.key === "Enter") handleSave();
              if (e.key === "Escape") onCancel();
            }}
          />
          <button
            type="button"
            onClick={() => setShowPassword(!showPassword)}
            className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
          >
            {showPassword ? (
              <EyeOff className="h-3.5 w-3.5" />
            ) : (
              <Eye className="h-3.5 w-3.5" />
            )}
          </button>
        </div>
        <button
          onClick={handleSave}
          disabled={!keyValue.trim() || isSaving}
          className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium bg-amber-500 hover:bg-amber-600 text-white transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isSaving ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Check className="h-3.5 w-3.5" />
          )}
          Save
        </button>
        <button
          onClick={onCancel}
          className="px-3 py-2 rounded-lg text-xs font-medium hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-500 transition-colors"
        >
          Cancel
        </button>
      </div>
      {error && <p className="mt-2 text-xs text-red-500">{error}</p>}
    </div>
  );
}
