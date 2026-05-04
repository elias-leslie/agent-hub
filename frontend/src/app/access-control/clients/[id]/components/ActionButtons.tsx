import { Ban, Pencil, Play, Trash2 } from 'lucide-react'

interface ActionButtonsProps {
  clientStatus: string
  onEdit: () => void
  onSuspend: () => void
  onActivate: () => void
  onBlock: () => void
  isActivating: boolean
}

export function ActionButtons({
  clientStatus,
  onEdit,
  onSuspend,
  onActivate,
  onBlock,
  isActivating,
}: ActionButtonsProps) {
  return (
    <section className="panel-surface p-5 lg:p-6">
      <div>
        <p className="section-kicker">Controls</p>
        <h2 className="section-heading mt-2">Actions</h2>
        <p className="section-copy mt-2">
          Change policy, pause the client, or permanently block it from
          requesting access.
        </p>
      </div>
      <div className="mt-5 flex flex-wrap gap-3">
        <button type="button" onClick={onEdit} className="button-primary">
          <Pencil className="h-4 w-4" />
          Edit Settings
        </button>

        {clientStatus === 'active' && (
          <button
            type="button"
            onClick={onSuspend}
            className="button-secondary border-amber-500/20 bg-amber-500/10 text-amber-100 hover:bg-amber-500/15"
          >
            <Ban className="h-4 w-4" />
            Suspend
          </button>
        )}

        {clientStatus === 'suspended' && (
          <button
            type="button"
            onClick={onActivate}
            disabled={isActivating}
            className="button-secondary border-emerald-500/20 bg-emerald-500/10 text-emerald-100 hover:bg-emerald-500/15 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Play className="h-4 w-4" />
            Activate
          </button>
        )}

        {clientStatus !== 'blocked' && (
          <button
            type="button"
            onClick={onBlock}
            className="button-secondary border-rose-500/20 bg-rose-500/10 text-rose-200 hover:bg-rose-500/15"
          >
            <Trash2 className="h-4 w-4" />
            Block Permanently
          </button>
        )}
      </div>
    </section>
  )
}
