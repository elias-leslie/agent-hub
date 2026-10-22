'use client'

import {
  Activity,
  Bot,
  Brain,
  BrainCircuit,
  CalendarClock,
  CircleDollarSign,
  Cpu,
  History,
  LayoutDashboard,
  MessageSquare,
  ScrollText,
  Shield,
} from 'lucide-react'
import Link from 'next/link'
import { useEffect, useRef } from 'react'
import { cn } from '@/lib/utils'

interface NavItem {
  href: string
  label: string
  icon: React.ComponentType<{ className?: string }>
  description: string
}

interface NavSection {
  id: string
  label: string
  items: NavItem[]
}

type NavEntry = NavItem | NavSection

function isNavSection(entry: NavEntry): entry is NavSection {
  return 'items' in entry
}

const NAV_ENTRIES: NavEntry[] = [
  {
    href: '/chat',
    label: 'Chat',
    icon: MessageSquare,
    description: 'Primary agent workspace',
  },
  {
    href: '/dashboard',
    label: 'Dashboard',
    icon: LayoutDashboard,
    description: 'Overview & status',
  },
  {
    href: '/costs',
    label: 'Costs',
    icon: CircleDollarSign,
    description: 'Agent spend & plans',
  },
  {
    href: '/automations',
    label: 'Automations',
    icon: CalendarClock,
    description: 'Schedules, policy & runs',
  },
  {
    href: '/monitoring/requests',
    label: 'Monitoring',
    icon: Activity,
    description: 'Requests & metrics',
  },
  {
    href: '/sessions',
    label: 'Sessions',
    icon: History,
    description: 'History & logs',
  },
  {
    id: 'agents',
    label: 'Agents',
    items: [
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
        description: 'Semantic store',
      },
      {
        href: '/runtime-context',
        label: 'Agent context',
        icon: BrainCircuit,
        description: 'Instructions and memories for agents',
      },
    ],
  },
  {
    href: '/admin',
    label: 'Activity',
    icon: Activity,
    description: 'Work & admin activity',
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
}

function isActiveRoute(pathname: string, href: string) {
  if (href === '/dashboard') return pathname === '/dashboard'
  return pathname === href || pathname.startsWith(`${href}/`)
}

interface NavLinkProps {
  item: NavItem
  active: boolean
  isCollapsed: boolean
}

function NavLink({ item, active, isCollapsed }: NavLinkProps) {
  const Icon = item.icon
  const label = item.label

  return (
    <Link
      href={item.href}
      prefetch={false}
      data-active={active}
      aria-current={active ? 'page' : undefined}
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
      aria-label={isCollapsed ? label : undefined}
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
}

export function SidebarNav({ isCollapsed, pathname }: SidebarNavProps) {
  const navRef = useRef<HTMLElement>(null)

  // On short screens the nav scrolls; keep the active link visible.
  useEffect(() => {
    const active = navRef.current?.querySelector<HTMLElement>(
      '[aria-current="page"]',
    )
    active?.scrollIntoView({ block: 'nearest' })
  }, [pathname, isCollapsed])

  return (
    <nav ref={navRef} className="flex-1 space-y-1.5 overflow-y-auto px-3 py-3">
      {NAV_ENTRIES.map((entry) => {
        if (!isNavSection(entry)) {
          return (
            <NavLink
              key={entry.href}
              item={entry}
              active={isActiveRoute(pathname, entry.href)}
              isCollapsed={isCollapsed}
            />
          )
        }

        const headingId = `sidebar-nav-section-${entry.id}`
        return (
          <div
            key={entry.id}
            role="group"
            aria-labelledby={headingId}
            data-nav-section={entry.id}
            className="space-y-1.5 pt-2"
          >
            <p
              id={headingId}
              className={cn(
                'px-3 pb-0.5 text-[10px] font-medium uppercase tracking-[0.24em] text-slate-500',
                isCollapsed && 'sr-only',
              )}
            >
              {entry.label}
            </p>
            {isCollapsed && (
              <div
                aria-hidden="true"
                className="mx-2 border-t border-slate-800/80"
              />
            )}
            {entry.items.map((item) => (
              <NavLink
                key={item.href}
                item={item}
                active={isActiveRoute(pathname, item.href)}
                isCollapsed={isCollapsed}
              />
            ))}
          </div>
        )
      })}
    </nav>
  )
}
