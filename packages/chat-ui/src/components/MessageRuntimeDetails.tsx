import {
  Activity,
  DollarSign,
  FileText,
  Paperclip,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";
import type { ChatMessage, ChatPermissionRequest } from "../types/chat";
import { cn } from "../lib/utils";

interface MessageRuntimeDetailsProps {
  message: ChatMessage;
}

function formatBytes(bytes: number | undefined): string | null {
  if (bytes == null) return null;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatCost(cost: number | undefined): string | null {
  if (cost == null) return null;
  if (cost < 0.01) return `$${cost.toFixed(4)}`;
  return `$${cost.toFixed(2)}`;
}

function permissionTone(permission: ChatPermissionRequest): string {
  if (permission.status === "granted") return "border-emerald-500/25 bg-emerald-500/10 text-emerald-200";
  if (permission.status === "denied") return "border-rose-500/25 bg-rose-500/10 text-rose-200";
  return "border-amber-500/25 bg-amber-500/10 text-amber-200";
}

function contextTone(tone: NonNullable<ChatMessage["contextHints"]>[number]["tone"]): string {
  if (tone === "danger") return "text-rose-300";
  if (tone === "warning") return "text-amber-300";
  return "text-muted-foreground";
}

export function MessageRuntimeDetails({ message }: MessageRuntimeDetailsProps) {
  const hasUsage =
    message.inputTokens !== undefined ||
    message.outputTokens !== undefined ||
    message.thinkingTokens !== undefined ||
    message.costUsd !== undefined;
  const hasArtifacts = Boolean(message.artifacts?.length);
  const hasAttachments = Boolean(message.attachments?.length);
  const hasPermissions = Boolean(message.permissionRequests?.length);
  const hasContextHints = Boolean(message.contextHints?.length);

  if (!hasUsage && !hasArtifacts && !hasAttachments && !hasPermissions && !hasContextHints && !message.statusLabel) {
    return null;
  }

  return (
    <div className="mt-3 space-y-2 border-t border-current/10 pt-2 text-xs">
      {(message.statusLabel || hasUsage || hasContextHints) && (
        <div className="flex flex-wrap items-center gap-2 text-muted-foreground">
          {message.statusLabel ? (
            <span className="inline-flex items-center gap-1 rounded-md bg-muted px-1.5 py-0.5">
              <Activity className="h-3 w-3" />
              {message.statusLabel}
            </span>
          ) : null}
          {message.inputTokens !== undefined ? <span>In: {message.inputTokens}</span> : null}
          {message.outputTokens !== undefined ? <span>Out: {message.outputTokens}</span> : null}
          {message.thinkingTokens !== undefined ? <span>Think: {message.thinkingTokens}</span> : null}
          {message.costUsd !== undefined ? (
            <span className="inline-flex items-center gap-1">
              <DollarSign className="h-3 w-3" />
              {formatCost(message.costUsd)}
            </span>
          ) : null}
          {message.contextHints?.map((hint) => (
            <span key={`${hint.label}:${hint.value}`} className={contextTone(hint.tone)}>
              {hint.label} {hint.value}
            </span>
          ))}
        </div>
      )}

      {hasPermissions && (
        <div className="flex flex-wrap gap-1.5">
          {message.permissionRequests?.map((permission) => {
            const Icon = permission.status === "granted" ? ShieldCheck : ShieldAlert;
            return (
              <span
                key={permission.id}
                className={cn("inline-flex max-w-full items-center gap-1 rounded-md border px-1.5 py-0.5", permissionTone(permission))}
                title={permission.risk}
              >
                <Icon className="h-3 w-3 shrink-0" />
                <span className="truncate">{permission.action}</span>
                <span className="opacity-70">{permission.status}</span>
              </span>
            );
          })}
        </div>
      )}

      {hasArtifacts && (
        <div className="space-y-1">
          {message.artifacts?.map((artifact) => (
            <div key={artifact.id} className="rounded-md border border-border bg-muted/45 px-2 py-1.5">
              <div className="flex items-center gap-1.5 text-foreground">
                <FileText className="h-3.5 w-3.5 shrink-0" />
                <span className="truncate font-medium">{artifact.title}</span>
                <span className="shrink-0 text-[10px] uppercase tracking-wide text-muted-foreground">{artifact.type}</span>
              </div>
              {artifact.summary ? <p className="mt-0.5 text-muted-foreground">{artifact.summary}</p> : null}
            </div>
          ))}
        </div>
      )}

      {hasAttachments && (
        <div className="flex flex-wrap gap-1.5">
          {message.attachments?.map((attachment) => (
            <span key={attachment.id} className="inline-flex max-w-full items-center gap-1 rounded-md bg-muted px-1.5 py-0.5 text-muted-foreground">
              <Paperclip className="h-3 w-3 shrink-0" />
              <span className="truncate">{attachment.name}</span>
              {formatBytes(attachment.sizeBytes) ? <span className="opacity-70">{formatBytes(attachment.sizeBytes)}</span> : null}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
