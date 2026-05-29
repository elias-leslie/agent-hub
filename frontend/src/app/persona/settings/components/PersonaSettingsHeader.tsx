import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  FlaskConical,
  Loader2,
} from 'lucide-react'
import Link from 'next/link'
import { cn } from '@/lib/utils'
import { getPersonaDisplayName } from '../../utils/displayName'

interface PersonaSettingsHeaderProps {
  personaName?: string
  hasChanges: boolean
  isSaving: boolean
  saveSuccess: boolean
  saveError: boolean
  onSave: () => void
  backHref?: string
}

export function PersonaSettingsHeader({
  personaName,
  hasChanges,
  isSaving,
  saveSuccess,
  saveError,
  onSave,
  backHref = '/persona',
}: PersonaSettingsHeaderProps) {
  const displayName = getPersonaDisplayName(personaName)

  return (
    <header className="page-header">
      <div className="page-container px-4 lg:px-8">
        <div className="page-header-row">
          <div className="page-title-group">
            <Link href={backHref} className="icon-button" title="Back to chat">
              <ArrowLeft className="h-5 w-5" />
            </Link>
            <div className="page-title-icon">
              <FlaskConical className="h-5 w-5" />
            </div>
            <div className="page-title-stack">
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="page-title">Persona Settings</h1>
                <span className="page-pill">{displayName}</span>
              </div>
              <div className="page-meta">
                <span className="page-pill">Identity and runtime</span>
                <span
                  className={cn(
                    'page-pill',
                    hasChanges
                      ? 'border-amber-500/20 bg-amber-500/10 text-amber-100'
                      : 'border-slate-700/80 bg-slate-900/90 text-slate-400',
                  )}
                >
                  {hasChanges ? 'Pending changes' : 'Saved'}
                </span>
              </div>
            </div>
          </div>

          <div className="page-toolbar">
            {saveSuccess && !hasChanges && (
              <span className="page-pill border-emerald-500/20 bg-emerald-500/10 text-emerald-200">
                <CheckCircle2 className="h-3.5 w-3.5" />
                Saved
              </span>
            )}
            {saveError && (
              <span className="page-pill border-rose-500/20 bg-rose-500/10 text-rose-200">
                <AlertCircle className="h-3.5 w-3.5" />
                Failed to save
              </span>
            )}
            {hasChanges && (
              <button
                onClick={onSave}
                disabled={isSaving}
                className={cn(
                  'button-primary',
                  'disabled:opacity-50 disabled:cursor-not-allowed',
                )}
              >
                {isSaving ? (
                  <span className="flex items-center gap-1.5">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    Saving...
                  </span>
                ) : (
                  'Save Changes'
                )}
              </button>
            )}
          </div>
        </div>
      </div>
    </header>
  )
}
