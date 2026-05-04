'use client'

interface DoneWhenResult {
  text: string
  status: 'MET' | 'NOT_MET' | 'PARTIAL'
  evidence: string
}

interface CompletionGateData {
  confidence: number
  done_when_results: DoneWhenResult[]
  gaps: string[]
  summary: string
}

const STATUS_STYLES: Record<
  string,
  { bg: string; text: string; label: string }
> = {
  MET: { bg: 'bg-emerald-500/10', text: 'text-emerald-400', label: 'Met' },
  NOT_MET: { bg: 'bg-red-500/10', text: 'text-red-400', label: 'Not Met' },
  PARTIAL: {
    bg: 'bg-yellow-500/10',
    text: 'text-yellow-400',
    label: 'Partial',
  },
}

export function CompletionGateResult({ data }: { data: CompletionGateData }) {
  const confidenceColor =
    data.confidence >= 90
      ? 'text-emerald-400'
      : data.confidence >= 70
        ? 'text-yellow-400'
        : 'text-red-400'

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
          Completion Gate
        </h4>
        <span className={`text-sm font-mono font-bold ${confidenceColor}`}>
          {data.confidence}/100
        </span>
      </div>

      <div className="space-y-1">
        {data.done_when_results.map((result, i) => {
          const style = STATUS_STYLES[result.status] || STATUS_STYLES.NOT_MET
          return (
            <div key={i} className={`rounded px-2 py-1 ${style.bg}`}>
              <div className="flex items-start gap-2 text-xs">
                <span className={`font-medium flex-shrink-0 ${style.text}`}>
                  {style.label}
                </span>
                <span className="text-foreground/80">{result.text}</span>
              </div>
              {result.evidence && (
                <div className="text-xs text-muted-foreground mt-0.5 ml-12 font-mono">
                  {result.evidence}
                </div>
              )}
            </div>
          )
        })}
      </div>

      {data.gaps.length > 0 && (
        <div className="text-xs text-red-400">
          <span className="font-medium">Gaps: </span>
          {data.gaps.join(', ')}
        </div>
      )}
    </div>
  )
}
