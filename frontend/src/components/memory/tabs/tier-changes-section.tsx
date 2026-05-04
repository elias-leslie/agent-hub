import type { TierChangesSummary } from '@/lib/memory-api'

const CHANGE_COLORS: Record<string, string> = {
  self_heal: 'text-emerald-400',
  demotion: 'text-red-400',
  promotion: 'text-amber-400',
  retirement: 'text-slate-400',
}

interface TierChangeRowProps {
  entry: TierChangesSummary['recent'][number]
}

function TierChangeRow({ entry }: TierChangeRowProps) {
  const colorClass = CHANGE_COLORS[entry.change_type] ?? 'text-slate-400'
  return (
    <div className="flex items-center gap-2 px-2 py-1 text-[10px] rounded bg-slate-800/20">
      <span className={`font-medium ${colorClass}`}>
        {entry.change_type.replace('_', ' ')}
      </span>
      <span className="text-slate-600">|</span>
      <span className="text-slate-500">
        {entry.old_tier} → {entry.new_tier}
      </span>
      {entry.lifecycle_score_before != null &&
        entry.lifecycle_score_after != null && (
          <>
            <span className="text-slate-600">|</span>
            <span className="text-slate-500 font-mono">
              {(entry.lifecycle_score_before * 100).toFixed(0)} →{' '}
              {(entry.lifecycle_score_after * 100).toFixed(0)}
            </span>
          </>
        )}
      <span className="text-slate-600 ml-auto font-mono">
        {entry.episode_uuid.slice(0, 8)}
      </span>
    </div>
  )
}

interface TierChangesByTypeProps {
  byType: TierChangesSummary['by_type']
}

function TierChangesByType({ byType }: TierChangesByTypeProps) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
      {Object.entries(byType).map(([type, info]) => (
        <div
          key={type}
          className="p-2 rounded bg-slate-800/40 border border-slate-800/60"
        >
          <p
            className={`text-sm font-mono font-bold ${CHANGE_COLORS[type] ?? 'text-slate-300'}`}
          >
            {info.count}
          </p>
          <p className="text-[9px] text-slate-500 uppercase">
            {type.replace('_', ' ')}
          </p>
        </div>
      ))}
    </div>
  )
}

interface TierChangesSectionProps {
  data: TierChangesSummary | undefined
}

export function TierChangesSection({ data }: TierChangesSectionProps) {
  if (!data || data.total === 0) {
    return (
      <p className="text-xs text-slate-500 text-center py-4">
        No type changes recorded
      </p>
    )
  }

  return (
    <div className="space-y-3">
      <TierChangesByType byType={data.by_type} />
      {data.recent.length > 0 && (
        <div className="space-y-1 max-h-48 overflow-y-auto">
          {data.recent.slice(0, 10).map((entry, i) => (
            <TierChangeRow key={i} entry={entry} />
          ))}
        </div>
      )}
    </div>
  )
}
