"use client";

import { useEffect, useRef } from "react";
import {
  MessageSquare,
  CheckCircle,
  AlertCircle,
  Radio,
  Wrench,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { SessionEvent, SessionEventType } from "@/types/events";

interface EventStreamProps {
  /** Events to display */
  events: SessionEvent[];
  /** Maximum height before scrolling */
  maxHeight?: string;
  /** Show timestamps */
  showTimestamps?: boolean;
  /** Additional CSS classes */
  className?: string;
}

// Event type configuration
const EVENT_CONFIG: Record<
  SessionEventType,
  { icon: typeof MessageSquare; color: string; label: string }
> = {
  session_start: {
    icon: Radio,
    color: "text-purple-500 bg-purple-100 dark:bg-purple-900/30",
    label: "Started",
  },
  message: {
    icon: MessageSquare,
    color: "text-blue-500 bg-blue-100 dark:bg-blue-900/30",
    label: "Message",
  },
  tool_use: {
    icon: Wrench,
    color: "text-amber-500 bg-amber-100 dark:bg-amber-900/30",
    label: "Tool",
  },
  complete: {
    icon: CheckCircle,
    color: "text-green-500 bg-green-100 dark:bg-green-900/30",
    label: "Complete",
  },
  error: {
    icon: AlertCircle,
    color: "text-red-500 bg-red-100 dark:bg-red-900/30",
    label: "Error",
  },
};

function formatTimestamp(timestamp: string): string {
  try {
    const date = new Date(timestamp);
    return date.toLocaleTimeString("en-US", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
  } catch {
    return "--:--:--";
  }
}

function getEventSummary(event: SessionEvent): string {
  const data = event.data;

  switch (event.event_type) {
    case "session_start":
      if ("model" in data) {
        return `Model: ${data.model}`;
      }
      return "Session started";
    case "message":
      if ("role" in data && "content" in data) {
        const content =
          data.content.length > 50
            ? data.content.slice(0, 50) + "..."
            : data.content;
        return `${data.role}: ${content}`;
      }
      return "Message";
    case "tool_use":
      if ("tool_name" in data) {
        return `Tool: ${data.tool_name}`;
      }
      return "Tool use";
    case "complete":
      if ("input_tokens" in data && "output_tokens" in data) {
        return `Tokens: ${data.input_tokens} in / ${data.output_tokens} out`;
      }
      return "Completed";
    case "error":
      if ("error_message" in data) {
        return data.error_message;
      }
      return "Error occurred";
    default:
      return "Event";
  }
}

interface EventItemProps {
  event: SessionEvent;
  showTimestamp?: boolean;
  isLast?: boolean;
}

function EventItem({
  event,
  showTimestamp = true,
  isLast = false,
}: EventItemProps) {
  const config = EVENT_CONFIG[event.event_type];
  const Icon = config.icon;
  const summary = getEventSummary(event);

  return (
    <div className="relative flex gap-3">
      {/* Timeline line */}
      {!isLast && (
        <div className="absolute left-4 top-8 h-full w-px bg-border" />
      )}

      {/* Icon */}
      <div
        className={cn(
          "relative z-10 flex h-8 w-8 shrink-0 items-center justify-center rounded-full",
          config.color,
        )}
      >
        <Icon className="h-4 w-4" />
      </div>

      {/* Content */}
      <div className="flex-1 pb-4">
        <div className="flex items-baseline justify-between gap-2">
          <span className="font-medium text-sm">{config.label}</span>
          {showTimestamp && (
            <span className="text-xs text-muted-foreground font-mono">
              {formatTimestamp(event.timestamp)}
            </span>
          )}
        </div>
        <p className="text-sm text-muted-foreground mt-0.5 break-words">
          {summary}
        </p>
        <p className="text-xs text-muted-foreground/70 mt-0.5 font-mono">
          {event.session_id.slice(0, 8)}...
        </p>
      </div>
    </div>
  );
}

/**
 * EventStream - Vertical timeline of session events.
 *
 * Displays events with color-coded icons, timestamps, and summaries.
 * Auto-scrolls to latest event when new events arrive.
 */
export function EventStream({
  events,
  maxHeight = "400px",
  showTimestamps = true,
  className,
}: EventStreamProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const lastEventCountRef = useRef(events.length);

  // Auto-scroll to bottom when new events arrive
  useEffect(() => {
    if (events.length > lastEventCountRef.current && scrollRef.current) {
      scrollRef.current.scrollTo({
        top: scrollRef.current.scrollHeight,
        behavior: "smooth",
      });
    }
    lastEventCountRef.current = events.length;
  }, [events.length]);

  if (events.length === 0) {
    return (
      <div
        className={cn(
          "flex items-center justify-center p-8 text-muted-foreground",
          className,
        )}
      >
        <div className="text-center">
          <Radio className="h-8 w-8 mx-auto mb-2 opacity-50" />
          <p className="text-sm">Waiting for events...</p>
        </div>
      </div>
    );
  }

  return (
    <div
      ref={scrollRef}
      className={cn("overflow-y-auto p-4", className)}
      style={{ maxHeight }}
    >
      {events.map((event, index) => (
        <EventItem
          key={`${event.session_id}-${event.timestamp}-${index}`}
          event={event}
          showTimestamp={showTimestamps}
          isLast={index === events.length - 1}
        />
      ))}
    </div>
  );
}
