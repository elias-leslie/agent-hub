"use client";

import { useState, useRef, useEffect } from "react";
import { MANUAL_PASTE, PROVIDER_ID_CLAUDE } from "./ProviderCardUtils";

interface ManualPasteInputProps {
  providerId: string;
  onSubmit: (input: string) => void;
  onCancel: () => void;
}

export function ManualPasteInput({
  providerId,
  onSubmit,
  onCancel,
}: ManualPasteInputProps) {
  const [value, setValue] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const isClaude = providerId === PROVIDER_ID_CLAUDE;
  const hint = isClaude ? MANUAL_PASTE.CLAUDE_HINT : MANUAL_PASTE.DEFAULT_HINT;
  const placeholder = isClaude
    ? MANUAL_PASTE.CLAUDE_PLACEHOLDER
    : MANUAL_PASTE.DEFAULT_PLACEHOLDER;

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && value.trim()) {
      onSubmit(value.trim());
    } else if (e.key === "Escape") {
      onCancel();
    }
  }

  return (
    <div className="mt-3 space-y-2">
      <p className="text-xs text-slate-500 dark:text-slate-400">{hint}</p>
      <div className="flex gap-2">
        <input
          ref={inputRef}
          type="text"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          className="flex-1 px-3 py-1.5 text-xs rounded-md border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono"
        />
        <button
          onClick={() => value.trim() && onSubmit(value.trim())}
          disabled={!value.trim()}
          className="px-3 py-1.5 text-xs font-medium rounded-md bg-blue-500 hover:bg-blue-600 text-white transition-colors disabled:opacity-50"
        >
          Submit
        </button>
        <button
          onClick={onCancel}
          className="px-3 py-1.5 text-xs font-medium rounded-md bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-400 transition-colors"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
