import {
  AlertTriangle,
  Bot,
  Brain,
  Database,
  MessageSquare,
  Sparkles,
  Terminal,
  User,
  Zap,
} from 'lucide-react'

export interface EventConfig {
  icon: typeof Brain
  label: string
  color: string
  bgColor: string
  borderColor: string
  glowColor: string
}

export const EVENT_CONFIGS: Record<string, EventConfig> = {
  user_message: {
    icon: User,
    label: 'User',
    color: 'text-sky-700 dark:text-sky-400',
    bgColor: 'bg-sky-500/10 dark:bg-sky-950/40',
    borderColor: 'border-sky-500/30 dark:border-sky-800/50',
    glowColor: 'shadow-sky-500/10',
  },
  assistant_message: {
    icon: Bot,
    label: 'Assistant',
    color: 'text-violet-700 dark:text-violet-400',
    bgColor: 'bg-violet-500/10 dark:bg-violet-950/40',
    borderColor: 'border-violet-500/30 dark:border-violet-800/50',
    glowColor: 'shadow-violet-500/10',
  },
  system_message: {
    icon: Sparkles,
    label: 'System',
    color: 'text-slate-400',
    bgColor: 'bg-slate-900/60',
    borderColor: 'border-slate-700/50',
    glowColor: 'shadow-slate-500/10',
  },
  thinking: {
    icon: Brain,
    label: 'Thinking',
    color: 'text-amber-700 dark:text-amber-400',
    bgColor: 'bg-amber-500/10 dark:bg-amber-950/30',
    borderColor: 'border-amber-500/30 dark:border-amber-700/40',
    glowColor: 'shadow-amber-500/10',
  },
  tool_use: {
    icon: Terminal,
    label: 'Tool Call',
    color: 'text-cyan-700 dark:text-cyan-400',
    bgColor: 'bg-cyan-500/10 dark:bg-cyan-950/30',
    borderColor: 'border-cyan-500/30 dark:border-cyan-700/40',
    glowColor: 'shadow-cyan-500/10',
  },
  tool_result: {
    icon: Zap,
    label: 'Tool Result',
    color: 'text-emerald-700 dark:text-emerald-400',
    bgColor: 'bg-emerald-500/10 dark:bg-emerald-950/30',
    borderColor: 'border-emerald-500/30 dark:border-emerald-700/40',
    glowColor: 'shadow-emerald-500/10',
  },
  memory_inject: {
    icon: Database,
    label: 'Memory Injected',
    color: 'text-rose-700 dark:text-rose-400',
    bgColor: 'bg-rose-500/10 dark:bg-rose-950/30',
    borderColor: 'border-rose-500/30 dark:border-rose-700/40',
    glowColor: 'shadow-rose-500/10',
  },
  memory_cite: {
    icon: Database,
    label: 'Memory Cited',
    color: 'text-pink-700 dark:text-pink-400',
    bgColor: 'bg-pink-500/10 dark:bg-pink-950/30',
    borderColor: 'border-pink-500/30 dark:border-pink-700/40',
    glowColor: 'shadow-pink-500/10',
  },
  error: {
    icon: AlertTriangle,
    label: 'Error',
    color: 'text-red-700 dark:text-red-400',
    bgColor: 'bg-red-500/10 dark:bg-red-950/40',
    borderColor: 'border-red-500/30 dark:border-red-700/50',
    glowColor: 'shadow-red-500/20',
  },
}

export function getEventConfig(eventType: string): EventConfig {
  return (
    EVENT_CONFIGS[eventType] || {
      icon: MessageSquare,
      label: eventType,
      color: 'text-slate-400',
      bgColor: 'bg-slate-900/40',
      borderColor: 'border-slate-700/50',
      glowColor: 'shadow-slate-500/10',
    }
  )
}
