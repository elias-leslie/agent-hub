export const TIER_COLORS: Record<string, string> = {
  mandate: '#ef4444',
  guardrail: '#f59e0b',
  reference: '#3b82f6',
}

export const TIER_LABELS: Record<string, string> = {
  mandate: 'Mandate',
  guardrail: 'Guardrail',
  reference: 'Reference',
}

export type ColorVariant =
  | 'emerald'
  | 'amber'
  | 'purple'
  | 'sky'
  | 'green'
  | 'rose'

export const COLOR_MAP: Record<
  ColorVariant,
  {
    border: string
    iconBg: string
    iconText: string
  }
> = {
  emerald: {
    border: 'border-l-emerald-500',
    iconBg: 'bg-emerald-500/10',
    iconText: 'text-emerald-400',
  },
  amber: {
    border: 'border-l-amber-500',
    iconBg: 'bg-amber-500/10',
    iconText: 'text-amber-400',
  },
  purple: {
    border: 'border-l-purple-500',
    iconBg: 'bg-purple-500/10',
    iconText: 'text-purple-400',
  },
  sky: {
    border: 'border-l-sky-500',
    iconBg: 'bg-sky-500/10',
    iconText: 'text-sky-400',
  },
  green: {
    border: 'border-l-green-500',
    iconBg: 'bg-green-500/10',
    iconText: 'text-green-400',
  },
  rose: {
    border: 'border-l-rose-500',
    iconBg: 'bg-rose-500/10',
    iconText: 'text-rose-400',
  },
}
