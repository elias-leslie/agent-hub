"use client";

export function PreferencesTab() {
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
