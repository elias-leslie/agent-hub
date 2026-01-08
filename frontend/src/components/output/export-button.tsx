"use client";

import { useState, useCallback } from "react";
import { Download, FileJson, FileText, Check, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ChatMessage } from "@/types/chat";

interface ExportButtonProps {
  messages: ChatMessage[];
  sessionId?: string;
  className?: string;
}

type ExportFormat = "markdown" | "json";

function formatMessagesAsMarkdown(messages: ChatMessage[], sessionId?: string): string {
  const header = `# Chat Export${sessionId ? ` - Session ${sessionId}` : ""}
Exported: ${new Date().toLocaleString()}
Messages: ${messages.length}

---

`;

  const body = messages
    .map((msg) => {
      const role = msg.role === "user" ? "User" : msg.agentName || "Assistant";
      const timestamp = msg.timestamp
        ? `\n*${new Date(msg.timestamp).toLocaleString()}*`
        : "";
      const edited = msg.edited ? " *(edited)*" : "";

      return `## ${role}${edited}${timestamp}

${msg.content}
`;
    })
    .join("\n---\n\n");

  return header + body;
}

function formatMessagesAsJson(messages: ChatMessage[], sessionId?: string): string {
  const exportData = {
    exportedAt: new Date().toISOString(),
    sessionId: sessionId || null,
    messageCount: messages.length,
    messages: messages.map((msg) => ({
      id: msg.id,
      role: msg.role,
      content: msg.content,
      agentName: msg.agentName || null,
      agentProvider: msg.agentProvider || null,
      timestamp: msg.timestamp || null,
      edited: msg.edited || false,
      inputTokens: msg.inputTokens,
      outputTokens: msg.outputTokens,
    })),
  };

  return JSON.stringify(exportData, null, 2);
}

function downloadFile(content: string, filename: string, mimeType: string) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

export function ExportButton({ messages, sessionId, className }: ExportButtonProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [exportedFormat, setExportedFormat] = useState<ExportFormat | null>(null);

  const handleExport = useCallback(
    (format: ExportFormat) => {
      const timestamp = new Date().toISOString().slice(0, 10);
      const sessionPart = sessionId ? `-${sessionId.slice(0, 8)}` : "";

      if (format === "markdown") {
        const content = formatMessagesAsMarkdown(messages, sessionId);
        downloadFile(content, `chat-export${sessionPart}-${timestamp}.md`, "text/markdown");
      } else {
        const content = formatMessagesAsJson(messages, sessionId);
        downloadFile(content, `chat-export${sessionPart}-${timestamp}.json`, "application/json");
      }

      setExportedFormat(format);
      setTimeout(() => {
        setExportedFormat(null);
        setIsOpen(false);
      }, 1500);
    },
    [messages, sessionId]
  );

  if (messages.length === 0) {
    return null;
  }

  return (
    <div className={cn("relative", className)}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        className={cn(
          "flex items-center gap-2 px-3 py-2 rounded-md",
          "text-sm font-medium",
          "bg-[oklch(0.96_0_0)] dark:bg-[oklch(0.18_0_0)]",
          "border border-[oklch(0.9_0_0)] dark:border-[oklch(0.25_0_0)]",
          "text-[oklch(0.4_0_0)] dark:text-[oklch(0.7_0_0)]",
          "hover:bg-[oklch(0.93_0_0)] dark:hover:bg-[oklch(0.22_0_0)]",
          "hover:border-[oklch(0.85_0_0)] dark:hover:border-[oklch(0.3_0_0)]",
          "transition-all duration-200",
          "focus:outline-none focus:ring-2 focus:ring-[oklch(0.6_0.1_250)] focus:ring-offset-2",
          "dark:focus:ring-offset-[oklch(0.145_0_0)]"
        )}
      >
        <Download className="w-4 h-4" />
        <span>Export</span>
        <ChevronDown
          className={cn("w-3.5 h-3.5 transition-transform duration-200", isOpen && "rotate-180")}
        />
      </button>

      {/* Dropdown menu */}
      {isOpen && (
        <>
          {/* Backdrop */}
          <div className="fixed inset-0 z-40" onClick={() => setIsOpen(false)} />

          {/* Menu */}
          <div
            className={cn(
              "absolute right-0 mt-2 w-48 z-50",
              "rounded-lg overflow-hidden",
              "bg-white dark:bg-[oklch(0.16_0_0)]",
              "border border-[oklch(0.9_0_0)] dark:border-[oklch(0.25_0_0)]",
              "shadow-lg dark:shadow-[0_4px_20px_oklch(0_0_0/0.4)]",
              "animate-in fade-in-0 zoom-in-95 duration-150"
            )}
          >
            <div className="py-1">
              <button
                onClick={() => handleExport("markdown")}
                className={cn(
                  "w-full flex items-center gap-3 px-4 py-2.5",
                  "text-sm text-left",
                  "text-[oklch(0.35_0_0)] dark:text-[oklch(0.75_0_0)]",
                  "hover:bg-[oklch(0.96_0_0)] dark:hover:bg-[oklch(0.2_0_0)]",
                  "transition-colors"
                )}
              >
                {exportedFormat === "markdown" ? (
                  <Check className="w-4 h-4 text-[oklch(0.55_0.15_145)]" />
                ) : (
                  <FileText className="w-4 h-4 text-[oklch(0.5_0_0)]" />
                )}
                <div>
                  <div className="font-medium">Markdown</div>
                  <div className="text-xs text-[oklch(0.55_0_0)] dark:text-[oklch(0.55_0_0)]">
                    Human-readable format
                  </div>
                </div>
              </button>

              <button
                onClick={() => handleExport("json")}
                className={cn(
                  "w-full flex items-center gap-3 px-4 py-2.5",
                  "text-sm text-left",
                  "text-[oklch(0.35_0_0)] dark:text-[oklch(0.75_0_0)]",
                  "hover:bg-[oklch(0.96_0_0)] dark:hover:bg-[oklch(0.2_0_0)]",
                  "transition-colors"
                )}
              >
                {exportedFormat === "json" ? (
                  <Check className="w-4 h-4 text-[oklch(0.55_0.15_145)]" />
                ) : (
                  <FileJson className="w-4 h-4 text-[oklch(0.5_0_0)]" />
                )}
                <div>
                  <div className="font-medium">JSON</div>
                  <div className="text-xs text-[oklch(0.55_0_0)] dark:text-[oklch(0.55_0_0)]">
                    Machine-readable format
                  </div>
                </div>
              </button>
            </div>

            {/* Footer with message count */}
            <div
              className={cn(
                "px-4 py-2 text-xs",
                "bg-[oklch(0.97_0_0)] dark:bg-[oklch(0.12_0_0)]",
                "border-t border-[oklch(0.92_0_0)] dark:border-[oklch(0.22_0_0)]",
                "text-[oklch(0.5_0_0)] dark:text-[oklch(0.5_0_0)]"
              )}
            >
              {messages.length} message{messages.length !== 1 ? "s" : ""} to export
            </div>
          </div>
        </>
      )}
    </div>
  );
}
