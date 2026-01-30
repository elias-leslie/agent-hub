interface PromptEditorProps {
  value: string;
  onChange: (value: string) => void;
}

export function PromptEditor({ value, onChange }: PromptEditorProps) {
  return (
    <div className="space-y-1.5">
      <label className="text-xs font-medium text-slate-600 dark:text-slate-400">
        System Prompt
      </label>
      <div className="relative">
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          rows={20}
          className="w-full px-4 py-3 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500/40 resize-y"
          placeholder="Enter system prompt..."
        />
        <div className="absolute bottom-2 right-2 text-[10px] text-slate-400 font-mono">
          {value.length} chars
        </div>
      </div>
      <p className="text-[10px] text-slate-400">
        Variables like {"{{variable}}"} will be highlighted. Mandates are injected based on tags.
      </p>
    </div>
  );
}
