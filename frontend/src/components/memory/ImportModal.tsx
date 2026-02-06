"use client";

import { useState, useRef } from "react";
import { Upload, X, Loader2, CheckCircle, AlertCircle, FileJson } from "lucide-react";
import { cn } from "@/lib/utils";
import { addEpisode } from "@/lib/memory-api";
import type { MemoryCategory, MemorySource } from "@/lib/memory-api";

interface ImportItem {
  content: string;
  source?: MemorySource;
  source_description?: string;
  category?: MemoryCategory;
  injection_tier?: MemoryCategory;
}

interface ImportResult {
  total: number;
  created: number;
  skipped: number;
  errors: string[];
}

export function ImportModal({
  isOpen,
  onClose,
  onImported,
}: {
  isOpen: boolean;
  onClose: () => void;
  onImported: () => void;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [items, setItems] = useState<ImportItem[]>([]);
  const [fileName, setFileName] = useState<string | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);
  const [progress, setProgress] = useState(0);
  const [result, setResult] = useState<ImportResult | null>(null);

  if (!isOpen) return null;

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setParseError(null);
    setResult(null);
    setFileName(file.name);

    const reader = new FileReader();
    reader.onload = (event) => {
      try {
        const data = JSON.parse(event.target?.result as string);
        const parsed: ImportItem[] = Array.isArray(data) ? data : data.episodes ?? [];

        if (parsed.length === 0) {
          setParseError("No episodes found in file");
          return;
        }

        const valid = parsed.filter((item) => item.content && typeof item.content === "string");
        if (valid.length === 0) {
          setParseError("No valid episodes (each must have a 'content' field)");
          return;
        }

        setItems(valid);
      } catch {
        setParseError("Invalid JSON file");
      }
    };
    reader.readAsText(file);
  };

  const handleImport = async () => {
    setImporting(true);
    setProgress(0);

    const importResult: ImportResult = { total: items.length, created: 0, skipped: 0, errors: [] };

    for (let i = 0; i < items.length; i++) {
      const item = items[i];
      try {
        await addEpisode({
          content: item.content,
          source: item.source ?? "system",
          source_description: item.source_description ?? "imported",
          injection_tier: item.injection_tier ?? item.category ?? "reference",
        });
        importResult.created++;
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Unknown error";
        if (importResult.errors.length < 5) {
          importResult.errors.push(`Item ${i + 1}: ${msg}`);
        }
        importResult.skipped++;
      }
      setProgress(Math.round(((i + 1) / items.length) * 100));
    }

    setResult(importResult);
    setImporting(false);

    if (importResult.created > 0) {
      onImported();
    }
  };

  const handleClose = () => {
    setItems([]);
    setFileName(null);
    setParseError(null);
    setResult(null);
    setProgress(0);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={handleClose} />

      <div className="relative w-full max-w-lg mx-4 rounded-xl bg-slate-900 shadow-2xl border border-slate-800">
        <div className="flex items-center justify-between p-4 border-b border-slate-800">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-full bg-blue-900/30">
              <Upload className="w-5 h-5 text-blue-400" />
            </div>
            <h2 className="text-lg font-semibold text-slate-100">Import Memories</h2>
          </div>
          <button
            onClick={handleClose}
            disabled={importing}
            className="p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800 disabled:opacity-50"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-4 space-y-4">
          {!result && (
            <>
              <div
                onClick={() => fileRef.current?.click()}
                className={cn(
                  "border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors",
                  "border-slate-700 hover:border-blue-600 hover:bg-blue-950/10"
                )}
              >
                <FileJson className="w-8 h-8 text-slate-500 mx-auto mb-2" />
                <p className="text-sm text-slate-300">
                  {fileName ?? "Click to select JSON file"}
                </p>
                <p className="text-xs text-slate-500 mt-1">
                  Accepts exported memory JSON (array of episodes)
                </p>
                <input
                  ref={fileRef}
                  type="file"
                  accept=".json"
                  onChange={handleFileSelect}
                  className="hidden"
                />
              </div>

              {parseError && (
                <div className="flex items-center gap-2 p-3 rounded-lg bg-red-900/20 border border-red-800">
                  <AlertCircle className="w-4 h-4 text-red-400 flex-shrink-0" />
                  <p className="text-sm text-red-400">{parseError}</p>
                </div>
              )}

              {items.length > 0 && (
                <div className="p-3 rounded-lg bg-slate-800/50 border border-slate-700">
                  <p className="text-sm text-slate-200">
                    <span className="font-mono font-bold text-emerald-400">{items.length}</span> episodes ready to import
                  </p>
                  <p className="text-xs text-slate-400 mt-1">
                    All will be imported as <span className="text-blue-400">reference</span> tier unless specified
                  </p>
                </div>
              )}

              {importing && (
                <div className="space-y-2">
                  <div className="flex items-center justify-between text-xs text-slate-400">
                    <span>Importing...</span>
                    <span className="font-mono">{progress}%</span>
                  </div>
                  <div className="h-2 rounded-full bg-slate-800 overflow-hidden">
                    <div
                      className="h-full rounded-full bg-emerald-500 transition-all duration-300"
                      style={{ width: `${progress}%` }}
                    />
                  </div>
                </div>
              )}
            </>
          )}

          {result && (
            <div className="space-y-3">
              <div className="flex items-center gap-3 p-4 rounded-lg bg-emerald-900/20 border border-emerald-800">
                <CheckCircle className="w-6 h-6 text-emerald-400 flex-shrink-0" />
                <div>
                  <p className="text-sm font-medium text-emerald-300">
                    Import complete
                  </p>
                  <p className="text-xs text-slate-400 mt-0.5">
                    {result.created} created, {result.skipped} skipped of {result.total}
                  </p>
                </div>
              </div>

              {result.errors.length > 0 && (
                <div className="p-3 rounded-lg bg-red-900/20 border border-red-800 space-y-1">
                  {result.errors.map((err, i) => (
                    <p key={i} className="text-xs text-red-400">{err}</p>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-3 p-4 border-t border-slate-800">
          <button
            onClick={handleClose}
            disabled={importing}
            className="px-4 py-2 rounded-lg text-sm font-medium text-slate-300 hover:bg-slate-800 disabled:opacity-50"
          >
            {result ? "Close" : "Cancel"}
          </button>
          {!result && (
            <button
              onClick={handleImport}
              disabled={items.length === 0 || importing}
              className="px-4 py-2 rounded-lg text-sm font-medium bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-50 flex items-center gap-2"
            >
              {importing ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Importing...
                </>
              ) : (
                <>
                  <Upload className="w-4 h-4" />
                  Import {items.length > 0 ? `(${items.length})` : ""}
                </>
              )}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
