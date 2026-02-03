"use client";

import { useState, useMemo } from "react";
import {
  Brain,
  MessageSquare,
  Terminal,
  Database,
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  User,
  Bot,
  Sparkles,
  Clock,
  Zap,
  Search,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { SessionTimelineEvent } from "@/lib/api";
import { CodeBlock } from "@/components/output/code-block";

type EventType = SessionTimelineEvent["event_type"];

interface EventConfig {
  icon: typeof Brain;
  label: string;
  color: string;
  bgColor: string;
  borderColor: string;
  glowColor: string;
}

const EVENT_CONFIGS: Record<string, EventConfig> = {
  user_message: {
    icon: User,
    label: "User",
    color: "text-sky-400",
    bgColor: "bg-sky-950/40",
    borderColor: "border-sky-800/50",
    glowColor: "shadow-sky-500/10",
  },
  assistant_message: {
    icon: Bot,
    label: "Assistant",
    color: "text-violet-400",
    bgColor: "bg-violet-950/40",
    borderColor: "border-violet-800/50",
    glowColor: "shadow-violet-500/10",
  },
  system_message: {
    icon: Sparkles,
    label: "System",
    color: "text-slate-400",
    bgColor: "bg-slate-900/60",
    borderColor: "border-slate-700/50",
    glowColor: "shadow-slate-500/10",
  },
  thinking: {
    icon: Brain,
    label: "Thinking",
    color: "text-amber-400",
    bgColor: "bg-amber-950/30",
    borderColor: "border-amber-700/40",
    glowColor: "shadow-amber-500/10",
  },
  tool_use: {
    icon: Terminal,
    label: "Tool Call",
    color: "text-cyan-400",
    bgColor: "bg-cyan-950/30",
    borderColor: "border-cyan-700/40",
    glowColor: "shadow-cyan-500/10",
  },
  tool_result: {
    icon: Zap,
    label: "Tool Result",
    color: "text-emerald-400",
    bgColor: "bg-emerald-950/30",
    borderColor: "border-emerald-700/40",
    glowColor: "shadow-emerald-500/10",
  },
  memory_inject: {
    icon: Database,
    label: "Memory Injected",
    color: "text-rose-400",
    bgColor: "bg-rose-950/30",
    borderColor: "border-rose-700/40",
    glowColor: "shadow-rose-500/10",
  },
  memory_cite: {
    icon: Database,
    label: "Memory Cited",
    color: "text-pink-400",
    bgColor: "bg-pink-950/30",
    borderColor: "border-pink-700/40",
    glowColor: "shadow-pink-500/10",
  },
  error: {
    icon: AlertTriangle,
    label: "Error",
    color: "text-red-400",
    bgColor: "bg-red-950/40",
    borderColor: "border-red-700/50",
    glowColor: "shadow-red-500/20",
  },
};

function getEventConfig(eventType: string): EventConfig {
  return (
    EVENT_CONFIGS[eventType] || {
      icon: MessageSquare,
      label: eventType,
      color: "text-slate-400",
      bgColor: "bg-slate-900/40",
      borderColor: "border-slate-700/50",
      glowColor: "shadow-slate-500/10",
    }
  );
}

function formatTimestamp(timestamp: string): string {
  const date = new Date(timestamp);
  return date.toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60000)}m ${Math.floor((ms % 60000) / 1000)}s`;
}

function formatTokens(tokens: number): string {
  if (tokens >= 1000000) return `${(tokens / 1000000).toFixed(1)}M`;
  if (tokens >= 1000) return `${(tokens / 1000).toFixed(1)}K`;
  return tokens.toString();
}

interface EventItemProps {
  event: SessionTimelineEvent;
  isFirst: boolean;
  isLast: boolean;
}

function EventItem({ event, isFirst, isLast }: EventItemProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const config = getEventConfig(event.event_type);
  const Icon = config.icon;

  const hasExpandableContent =
    (event.content && event.content.length > 200) ||
    event.tool_input ||
    event.tool_output;

  const truncatedContent = event.content
    ? event.content.length > 200 && !isExpanded
      ? event.content.slice(0, 200) + "..."
      : event.content
    : null;

  return (
    <div className="relative flex gap-3 group">
      {/* Timeline connector */}
      <div className="relative flex flex-col items-center">
        {/* Top line */}
        {!isFirst && (
          <div
            className={cn(
              "absolute top-0 w-px h-3",
              "bg-gradient-to-b from-slate-700/60 to-slate-700/30"
            )}
          />
        )}

        {/* Icon circle */}
        <div
          className={cn(
            "relative z-10 mt-3 flex items-center justify-center",
            "w-8 h-8 rounded-lg",
            config.bgColor,
            "border",
            config.borderColor,
            "shadow-lg",
            config.glowColor,
            "transition-all duration-200",
            "group-hover:scale-110"
          )}
        >
          <Icon className={cn("w-4 h-4", config.color)} />
        </div>

        {/* Bottom line */}
        {!isLast && (
          <div
            className={cn(
              "flex-1 w-px min-h-[2rem]",
              "bg-gradient-to-b from-slate-700/30 to-slate-700/60"
            )}
          />
        )}
      </div>

      {/* Event content */}
      <div className="flex-1 pb-4 min-w-0">
        <div
          className={cn(
            "rounded-lg border p-3",
            config.bgColor,
            config.borderColor,
            "shadow-lg",
            config.glowColor,
            "transition-all duration-200",
            hasExpandableContent && "cursor-pointer hover:border-opacity-70",
            isExpanded && "ring-1 ring-white/5"
          )}
          onClick={() => hasExpandableContent && setIsExpanded(!isExpanded)}
        >
          {/* Header row */}
          <div className="flex items-center justify-between gap-2 mb-2">
            <div className="flex items-center gap-2 min-w-0">
              <span className={cn("text-sm font-semibold tracking-wide", config.color)}>
                {config.label}
              </span>

              {event.tool_name && (
                <span className="px-2 py-0.5 rounded bg-slate-800/60 text-xs font-mono text-slate-300 truncate max-w-[200px]">
                  {event.tool_name}
                </span>
              )}

              {event.agent_name && (
                <span className="px-2 py-0.5 rounded bg-slate-800/60 text-xs text-slate-400">
                  {event.agent_name}
                </span>
              )}
            </div>

            <div className="flex items-center gap-3 text-xs text-slate-500 shrink-0">
              {event.tokens && (
                <span className="flex items-center gap-1 font-mono">
                  <Sparkles className="w-3 h-3" />
                  {formatTokens(event.tokens)}
                </span>
              )}

              {event.duration_ms && (
                <span className="flex items-center gap-1 font-mono">
                  <Clock className="w-3 h-3" />
                  {formatDuration(event.duration_ms)}
                </span>
              )}

              <span className="font-mono tabular-nums">
                {formatTimestamp(event.created_at)}
              </span>

              {hasExpandableContent && (
                <span className="text-slate-600">
                  {isExpanded ? (
                    <ChevronDown className="w-4 h-4" />
                  ) : (
                    <ChevronRight className="w-4 h-4" />
                  )}
                </span>
              )}
            </div>
          </div>

          {/* Content */}
          {truncatedContent && (
            <div
              className={cn(
                "text-sm text-slate-300 whitespace-pre-wrap break-words",
                "font-mono leading-relaxed",
                event.event_type === "thinking" && "italic text-amber-200/80"
              )}
            >
              {truncatedContent}
            </div>
          )}

          {/* Expanded tool details */}
          {isExpanded && (event.tool_input || event.tool_output) && (
            <div className="mt-3 space-y-3">
              {event.tool_input && (
                <div>
                  <div className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">
                    Input
                  </div>
                  <CodeBlock
                    code={JSON.stringify(event.tool_input, null, 2)}
                    language="json"
                    maxHeight={300}
                    showLineNumbers={false}
                  />
                </div>
              )}

              {event.tool_output && (
                <div>
                  <div className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">
                    Output
                  </div>
                  <CodeBlock
                    code={
                      typeof event.tool_output === "string"
                        ? event.tool_output
                        : JSON.stringify(event.tool_output, null, 2)
                    }
                    language="json"
                    maxHeight={300}
                    showLineNumbers={false}
                  />
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

interface TurnGroupProps {
  turn: number;
  events: SessionTimelineEvent[];
  isLast: boolean;
}

function TurnGroup({ turn, events, isLast }: TurnGroupProps) {
  const [isCollapsed, setIsCollapsed] = useState(false);

  return (
    <div className="relative">
      {/* Turn header */}
      <button
        onClick={() => setIsCollapsed(!isCollapsed)}
        className={cn(
          "sticky top-0 z-10 w-full flex items-center gap-3 py-2 px-3 mb-3",
          "bg-slate-950/95 backdrop-blur-sm",
          "border-b border-slate-800/60",
          "hover:bg-slate-900/80 transition-colors",
          "text-left"
        )}
      >
        <div className="flex items-center gap-2">
          {isCollapsed ? (
            <ChevronRight className="w-4 h-4 text-slate-500" />
          ) : (
            <ChevronDown className="w-4 h-4 text-slate-500" />
          )}
          <span className="text-xs font-semibold uppercase tracking-widest text-slate-500">
            Turn {turn}
          </span>
        </div>
        <div className="flex-1 h-px bg-gradient-to-r from-slate-800 to-transparent" />
        <span className="text-xs text-slate-600 font-mono">
          {events.length} event{events.length !== 1 ? "s" : ""}
        </span>
      </button>

      {/* Events */}
      {!isCollapsed && (
        <div className="pl-2">
          {events.map((event, idx) => (
            <EventItem
              key={event.id}
              event={event}
              isFirst={idx === 0}
              isLast={idx === events.length - 1 && isLast}
            />
          ))}
        </div>
      )}
    </div>
  );
}

interface FilterChipProps {
  label: string;
  eventType: EventType;
  isActive: boolean;
  count: number;
  onClick: () => void;
}

function FilterChip({ label, eventType, isActive, count, onClick }: FilterChipProps) {
  const config = getEventConfig(eventType);
  const Icon = config.icon;

  return (
    <button
      onClick={onClick}
      className={cn(
        "flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg",
        "text-xs font-medium tracking-wide",
        "border transition-all duration-200",
        isActive
          ? cn(config.bgColor, config.borderColor, config.color)
          : "bg-slate-900/40 border-slate-800/50 text-slate-500 hover:text-slate-400 hover:border-slate-700"
      )}
    >
      <Icon className="w-3.5 h-3.5" />
      <span>{label}</span>
      <span
        className={cn(
          "px-1.5 py-0.5 rounded text-[10px] font-mono",
          isActive ? "bg-white/10" : "bg-slate-800/60"
        )}
      >
        {count}
      </span>
    </button>
  );
}

interface EventTimelineProps {
  events: SessionTimelineEvent[];
  className?: string;
}

export function EventTimeline({ events, className }: EventTimelineProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const [activeFilters, setActiveFilters] = useState<Set<EventType>>(new Set());

  // Count events by type
  const eventCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    events.forEach((e) => {
      counts[e.event_type] = (counts[e.event_type] || 0) + 1;
    });
    return counts;
  }, [events]);

  // Filter events
  const filteredEvents = useMemo(() => {
    return events.filter((e) => {
      // Filter by type
      if (activeFilters.size > 0 && !activeFilters.has(e.event_type as EventType)) {
        return false;
      }
      // Filter by search
      if (searchQuery) {
        const query = searchQuery.toLowerCase();
        return (
          e.content?.toLowerCase().includes(query) ||
          e.tool_name?.toLowerCase().includes(query) ||
          e.agent_name?.toLowerCase().includes(query) ||
          JSON.stringify(e.tool_input)?.toLowerCase().includes(query) ||
          JSON.stringify(e.tool_output)?.toLowerCase().includes(query)
        );
      }
      return true;
    });
  }, [events, activeFilters, searchQuery]);

  // Group by turn
  const groupedByTurn = useMemo(() => {
    const groups: Map<number, SessionTimelineEvent[]> = new Map();
    filteredEvents.forEach((event) => {
      const existing = groups.get(event.turn) || [];
      existing.push(event);
      groups.set(event.turn, existing);
    });
    return Array.from(groups.entries()).sort((a, b) => a[0] - b[0]);
  }, [filteredEvents]);

  const toggleFilter = (eventType: EventType) => {
    setActiveFilters((prev) => {
      const next = new Set(prev);
      if (next.has(eventType)) {
        next.delete(eventType);
      } else {
        next.add(eventType);
      }
      return next;
    });
  };

  const allEventTypes: EventType[] = [
    "user_message",
    "assistant_message",
    "thinking",
    "tool_use",
    "tool_result",
    "memory_inject",
    "memory_cite",
    "error",
  ];

  const presentEventTypes = allEventTypes.filter((t) => eventCounts[t] > 0);

  return (
    <div className={cn("flex flex-col h-full", className)}>
      {/* Filters header */}
      <div className="sticky top-0 z-20 bg-slate-950/95 backdrop-blur-sm border-b border-slate-800/60 p-4 space-y-3">
        {/* Search */}
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search events..."
            className={cn(
              "w-full pl-9 pr-9 py-2 rounded-lg",
              "bg-slate-900/60 border border-slate-800/60",
              "text-sm text-slate-300 placeholder:text-slate-600",
              "focus:outline-none focus:ring-1 focus:ring-slate-700 focus:border-slate-700",
              "transition-all duration-200"
            )}
          />
          {searchQuery && (
            <button
              onClick={() => setSearchQuery("")}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-400"
            >
              <X className="w-4 h-4" />
            </button>
          )}
        </div>

        {/* Filter chips */}
        <div className="flex flex-wrap gap-2">
          {presentEventTypes.map((eventType) => (
            <FilterChip
              key={eventType}
              label={EVENT_CONFIGS[eventType]?.label || eventType}
              eventType={eventType}
              isActive={activeFilters.has(eventType)}
              count={eventCounts[eventType] || 0}
              onClick={() => toggleFilter(eventType)}
            />
          ))}

          {activeFilters.size > 0 && (
            <button
              onClick={() => setActiveFilters(new Set())}
              className="flex items-center gap-1 px-2 py-1.5 text-xs text-slate-500 hover:text-slate-400 transition-colors"
            >
              <X className="w-3 h-3" />
              Clear filters
            </button>
          )}
        </div>
      </div>

      {/* Timeline */}
      <div className="flex-1 overflow-y-auto p-4">
        {groupedByTurn.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-slate-500">
            <Database className="w-12 h-12 mb-3 opacity-30" />
            <p className="text-sm">No events found</p>
            {(searchQuery || activeFilters.size > 0) && (
              <p className="text-xs text-slate-600 mt-1">
                Try adjusting your filters
              </p>
            )}
          </div>
        ) : (
          <div className="space-y-2">
            {groupedByTurn.map(([turn, turnEvents], idx) => (
              <TurnGroup
                key={turn}
                turn={turn}
                events={turnEvents}
                isLast={idx === groupedByTurn.length - 1}
              />
            ))}
          </div>
        )}
      </div>

      {/* Footer stats */}
      <div className="border-t border-slate-800/60 px-4 py-2 bg-slate-950/80">
        <div className="flex items-center justify-between text-xs text-slate-600">
          <span>
            {filteredEvents.length} of {events.length} events
          </span>
          <span className="font-mono">
            {groupedByTurn.length} turn{groupedByTurn.length !== 1 ? "s" : ""}
          </span>
        </div>
      </div>
    </div>
  );
}
