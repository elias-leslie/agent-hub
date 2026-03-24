import Link from "next/link";
import {
  LayoutDashboard,
  History,
  Activity,
  Bot,
  Brain,
  Shield,
  ScrollText,
  Cpu,
  User,
  FlaskConical,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface NavItem {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  description: string;
}

const NAV_ITEMS: NavItem[] = [
  {
    href: "/persona",
    label: "Persona",
    icon: User,
    description: "Your AI companion",
  },
  {
    href: "/dashboard",
    label: "Dashboard",
    icon: LayoutDashboard,
    description: "Overview & status",
  },
  {
    href: "/monitoring/requests",
    label: "Monitoring",
    icon: Activity,
    description: "Requests & metrics",
  },
  {
    href: "/arena",
    label: "Arena",
    icon: FlaskConical,
    description: "Benchmark command center",
  },
  {
    href: "/sessions",
    label: "Sessions",
    icon: History,
    description: "History & logs",
  },
  {
    href: "/agents",
    label: "Agents",
    icon: Bot,
    description: "Agent management",
  },
  {
    href: "/models",
    label: "Models",
    icon: Cpu,
    description: "Model catalog",
  },
  {
    href: "/prompts",
    label: "Prompts",
    icon: ScrollText,
    description: "Prompt templates",
  },
  {
    href: "/memory",
    label: "Memory",
    icon: Brain,
    description: "Knowledge graph",
  },
  {
    href: "/access-control",
    label: "Access Control",
    icon: Shield,
    description: "Client authentication",
  },
];

interface SidebarNavProps {
  isCollapsed: boolean;
  pathname: string;
  personaName?: string;
}

export function SidebarNav({ isCollapsed, pathname, personaName }: SidebarNavProps) {
  const isActive = (href: string) => {
    if (href === "/dashboard") return pathname === "/dashboard";
    return pathname.startsWith(href);
  };

  return (
    <nav className="flex-1 px-2 py-2 space-y-0.5 overflow-y-auto">
      {NAV_ITEMS.map((item) => {
        const active = isActive(item.href);
        const Icon = item.icon;
        const label = item.href === "/persona" && personaName ? personaName : item.label;

        return (
          <Link
            key={item.href}
            href={item.href}
            prefetch={false}
            data-active={active}
            className={cn(
              "nav-item-hover flex items-center gap-2.5 px-2.5 py-2 rounded-lg",
              "transition-colors duration-150",
              "focus-ring-amber",
              active
                ? "bg-amber-950/30 text-amber-400"
                : "text-slate-400 hover:bg-slate-800 hover:text-slate-200",
              isCollapsed && "lg:justify-center lg:px-0",
            )}
            title={isCollapsed ? label : undefined}
          >
            <Icon
              className={cn(
                "h-[18px] w-[18px] flex-shrink-0",
                active && "text-amber-400",
              )}
            />
            {!isCollapsed && (
              <span className="text-[13px] font-medium hidden lg:block truncate">
                {label}
              </span>
            )}
            {/* Mobile always shows labels */}
            <div className="lg:hidden">
              <span className="text-[13px] font-medium">{label}</span>
              <p className="text-[10px] text-slate-500">
                {item.description}
              </p>
            </div>
          </Link>
        );
      })}
    </nav>
  );
}
