'use client'

import { Palette } from 'lucide-react'
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
              Applies to every Agent Hub page. System follows your device
              setting and switches when it changes.
            </p>
          </div>
        </div>
        <ThemeSelector />
      </section>
    </div>
  )
}
