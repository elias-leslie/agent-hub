import {
  Activity,
  Bot,
  Brain,
  BrainCircuit,
  Cpu,
  FlaskConical,
  Gauge,
  History,
  LayoutDashboard,
  MessageSquare,
  ScrollText,
  Shield,
  User,
} from 'lucide-react'
import Link from 'next/link'
import { cn } from '@/lib/utils'

interface NavItem {
  href: string
  label: string
  icon: React.ComponentType<{ className?: string }>
  description: string
}

const NAV_ITEMS: NavItem[] = [
  {
    href: '/chat',
    label: 'Chat',
    icon: MessageSquare,
    description: 'Primary agent workspace',
  },
  {
    href: '/persona',
    label: 'Persona',
    icon: User,
    description: 'Workspace & automation',
  },
  {
    href: '/dashboard',
    label: 'Dashboard',
    icon: LayoutDashboard,
    description: 'Overview & status',
  },
  {
    href: '/monitoring/requests',
    label: 'Monitoring',
    icon: Activity,
    description: 'Requests & metrics',
  },
  {
    href: '/arena',
    label: 'Arena',
    icon: FlaskConical,
    description: 'Benchmark command center',
  },
  {
    href: '/sessions',
    label: 'Sessions',
    icon: History,
    description: 'History & logs',
  },
  {
    href: '/agents',
    label: 'Agents',
    icon: Bot,
    description: 'Agent management',
  },
  {
    href: '/models',
    label: 'Models',
    icon: Cpu,
    description: 'Model catalog',
  },
  {
    href: '/prompts',
    label: 'Prompts',
    icon: ScrollText,
    description: 'Prompt templates',
  },
  {
    href: '/memory',
    label: 'Memory',
    icon: Brain,
    description: 'Knowledge graph',
  },
  {
    href: '/runtime-context',
    label: 'Runtime Context',
    icon: BrainCircuit,
    description: 'CLI/TUI injection',
  },
  {
    href: '/compactness',
    label: 'Compactness',
    icon: Gauge,
    description: 'Caveman gate caps',
  },
  {
    href: '/access-control',
    label: 'Access Control',
    icon: Shield,
    description: 'Client authentication',
  },
]

interface SidebarNavProps {
  isCollapsed: boolean
  pathname: string
  personaName?: string
}

export function SidebarNav({
  isCollapsed,
  pathname,
  personaName,
}: SidebarNavProps) {
  const isActive = (href: string) => {
    if (href === '/dashboard') return pathname === '/dashboard'
    return pathname.startsWith(href)
  }

  return (
    <nav className="flex-1 space-y-1.5 overflow-y-auto px-3 py-3">
      {NAV_ITEMS.map((item) => {
        const active = isActive(item.href)
        const Icon = item.icon
        const label =
          item.href === '/persona' && personaName ? personaName : item.label

        return (
          <Link
            key={item.href}
            href={item.href}
            prefetch={false}
            data-active={active}
            className={cn(
              'nav-item-hover flex items-center gap-3 rounded-2xl px-3 py-3',
              'transition-all duration-150',
              'focus-ring-amber',
              active
                ? 'bg-[linear-gradient(135deg,rgba(120,53,15,0.7),rgba(69,26,3,0.2))] text-amber-100 shadow-[0_16px_40px_-30px_rgba(245,158,11,0.6)] ring-1 ring-amber-400/15'
                : 'text-slate-400 hover:bg-slate-800/80 hover:text-slate-100',
              isCollapsed && 'lg:justify-center lg:px-0 lg:py-3.5',
            )}
            title={isCollapsed ? label : undefined}
          >
            <div
              className={cn(
                'flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-xl border transition-colors',
                active
                  ? 'border-amber-400/20 bg-amber-500/10 text-amber-300'
                  : 'border-slate-800 bg-slate-900/70 text-slate-500',
              )}
            >
              <Icon className="h-[18px] w-[18px]" />
            </div>
            {!isCollapsed && (
              <div className="min-w-0 flex-1">
                <p className="truncate text-[13px] font-medium leading-tight">
                  {label}
                </p>
                <p
                  className={cn(
                    'mt-1 text-[11px] leading-tight',
                    active ? 'text-amber-100/60' : 'text-slate-500',
                  )}
                >
                  {item.description}
                </p>
              </div>
            )}
          </Link>
        )
      })}
    </nav>
  )
}
