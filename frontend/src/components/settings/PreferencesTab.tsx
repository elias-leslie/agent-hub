'use client'

import { Palette, SunMoon } from 'lucide-react'
import { ThemeSelector } from '@/components/theme-selector'

export function PreferencesTab() {
  return (
    <div className="space-y-6">
      <section className="section-card space-y-4">
        <div className="flex items-start gap-3">
          <div className="page-title-icon h-11 w-11 rounded-2xl">
            <Palette className="h-5 w-5" />
          </div>
          <div className="space-y-1">
            <h3 className="text-sm font-semibold text-slate-100">Appearance</h3>
            <p className="text-sm text-slate-400">
              Choose the default look for the dashboard. System mode respects
              your device preference and updates automatically when it changes.
            </p>
          </div>
        </div>
        <ThemeSelector />
      </section>

      <section className="section-card space-y-3">
        <div className="flex items-start gap-3">
          <div className="page-title-icon h-11 w-11 rounded-2xl">
            <SunMoon className="h-5 w-5" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-slate-100">
              Release-ready defaults
            </h3>
            <p className="text-sm text-slate-400">
              This tab now exposes only live, working preferences. Removed the
              placeholder response and model settings that were not actually
              persisted anywhere.
            </p>
          </div>
        </div>
        <p className="text-xs text-slate-500">
          Theme preference is stored locally and applies immediately across the
          app shell.
        </p>
      </section>
    </div>
  )
}
