import { BookOpen, Flame, Pencil, ShieldOff } from 'lucide-react'

export const TIER_CONFIG = {
  off: {
    label: 'Off',
    icon: ShieldOff,
    color: 'text-slate-400',
    bg: 'bg-slate-500/10',
    border: 'border-l-slate-600',
    dot: 'bg-slate-500',
    description: 'No automation access',
  },
  read: {
    label: 'Read',
    icon: BookOpen,
    color: 'text-amber-400',
    bg: 'bg-blue-500/10',
    border: 'border-l-blue-500',
    dot: 'bg-blue-500',
    description: 'Read files, consult agents',
  },
  write: {
    label: 'Write',
    icon: Pencil,
    color: 'text-amber-400',
    bg: 'bg-amber-500/10',
    border: 'border-l-amber-500',
    dot: 'bg-amber-500',
    description: 'Read + write files',
  },
  yolo: {
    label: 'YOLO',
    icon: Flame,
    color: 'text-emerald-400',
    bg: 'bg-emerald-500/10',
    border: 'border-l-emerald-500',
    dot: 'bg-emerald-500',
    description: 'Full access including bash',
  },
} as const

export type Tier = keyof typeof TIER_CONFIG
export const TIERS: Tier[] = ['off', 'read', 'write', 'yolo']

export function formatHour(hour: number): string {
  if (hour === 0 || hour === 24) return '12:00 AM'
  if (hour === 12) return '12:00 PM'
  return hour < 12 ? `${hour}:00 AM` : `${hour - 12}:00 PM`
}
