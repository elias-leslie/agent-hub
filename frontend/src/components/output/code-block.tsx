"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Prism from "prismjs";
import "prismjs/components/prism-typescript";
import "prismjs/components/prism-javascript";
import "prismjs/components/prism-python";
import "prismjs/components/prism-bash";
import "prismjs/components/prism-json";
import "prismjs/components/prism-css";
import "prismjs/components/prism-jsx";
import "prismjs/components/prism-tsx";
import "prismjs/components/prism-sql";
import "prismjs/components/prism-yaml";
import "prismjs/components/prism-markdown";
import "prismjs/components/prism-rust";
import "prismjs/components/prism-go";
import { Check, Copy, FileCode2 } from "lucide-react";
import { cn } from "@/lib/utils";

// Language detection heuristics
const LANGUAGE_PATTERNS: [RegExp, string][] = [
  [/^(import|from)\s+[\w.]+|def\s+\w+\(|class\s+\w+:|if\s+__name__\s*==/, "python"],
  [/^(import|export)\s+.*from\s+['"]|const\s+\w+\s*[:=]|=>\s*\{|async\s+function/, "typescript"],
  [/^function\s+\w+\(|var\s+\w+\s*=|===|!==/, "javascript"],
  [/<\w+[^>]*>.*<\/\w+>|className=/, "tsx"],
  [/^\s*\{[\s\S]*"[\w]+"\s*:/, "json"],
  [/^(SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP)\s+/i, "sql"],
  [/^\$\s+|^#!\/bin\/(ba)?sh|^(sudo|apt|npm|yarn|cd|ls|grep|cat)\s+/, "bash"],
  [/^(fn|let\s+mut|impl|struct|enum|pub\s+fn)\s+/, "rust"],
  [/^(package|func|import\s+\(|type\s+\w+\s+struct)/, "go"],
  [/^[\w-]+:\s*[^{]|^\s+-\s+\w+/, "yaml"],
  [/^#\s+|^\*\*\w+\*\*|^\[[\w\s]+\]\(/, "markdown"],
  [/^@[\w-]+\s*\{|^\.\w+\s*\{|^#\w+\s*\{/, "css"],
];

function detectLanguage(code: string): string {
  const trimmed = code.trim();
  for (const [pattern, lang] of LANGUAGE_PATTERNS) {
    if (pattern.test(trimmed)) {
      return lang;
    }
  }
  return "text";
}

// Language display names
const LANGUAGE_LABELS: Record<string, string> = {
  typescript: "TypeScript",
  javascript: "JavaScript",
  python: "Python",
  bash: "Bash",
  json: "JSON",
  css: "CSS",
  jsx: "JSX",
  tsx: "TSX",
  sql: "SQL",
  yaml: "YAML",
  markdown: "Markdown",
  rust: "Rust",
  go: "Go",
  text: "Plain Text",
};

interface CodeBlockProps {
  code: string;
  language?: string;
  filename?: string;
  showLineNumbers?: boolean;
  maxHeight?: number;
  className?: string;
}

export function CodeBlock({
  code,
  language,
  filename,
  showLineNumbers = true,
  maxHeight = 400,
  className,
}: CodeBlockProps) {
  const codeRef = useRef<HTMLElement>(null);
  const [copied, setCopied] = useState(false);
  const detectedLang = language || detectLanguage(code);
  const displayLang = LANGUAGE_LABELS[detectedLang] || detectedLang;

  useEffect(() => {
    if (codeRef.current) {
      Prism.highlightElement(codeRef.current);
    }
  }, [code, detectedLang]);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback for older browsers
      const textarea = document.createElement("textarea");
      textarea.value = code;
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand("copy");
      document.body.removeChild(textarea);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  }, [code]);

  const lines = code.split("\n");

  return (
    <div
      className={cn(
        "group relative rounded-lg overflow-hidden",
        "bg-[oklch(0.12_0_0)] dark:bg-[oklch(0.08_0_0)]",
        "border border-[oklch(0.25_0_0)] dark:border-[oklch(0.2_0_0)]",
        "shadow-[0_2px_8px_oklch(0_0_0/0.15)] dark:shadow-[0_2px_12px_oklch(0_0_0/0.4)]",
        "font-mono text-sm",
        className
      )}
    >
      {/* Header bar with terminal aesthetic */}
      <div
        className={cn(
          "flex items-center justify-between px-3 py-2",
          "bg-[oklch(0.16_0_0)] dark:bg-[oklch(0.1_0_0)]",
          "border-b border-[oklch(0.25_0_0)] dark:border-[oklch(0.18_0_0)]"
        )}
      >
        <div className="flex items-center gap-2">
          {/* Terminal dots */}
          <div className="flex gap-1.5 mr-2">
            <div className="w-2.5 h-2.5 rounded-full bg-[oklch(0.65_0.2_25)]" />
            <div className="w-2.5 h-2.5 rounded-full bg-[oklch(0.75_0.15_85)]" />
            <div className="w-2.5 h-2.5 rounded-full bg-[oklch(0.7_0.15_145)]" />
          </div>

          {filename ? (
            <div className="flex items-center gap-1.5 text-[oklch(0.7_0_0)]">
              <FileCode2 className="w-3.5 h-3.5" />
              <span className="text-xs font-medium tracking-wide">{filename}</span>
            </div>
          ) : (
            <span className="text-xs font-medium tracking-wider uppercase text-[oklch(0.55_0_0)]">
              {displayLang}
            </span>
          )}
        </div>

        <button
          onClick={handleCopy}
          className={cn(
            "flex items-center gap-1.5 px-2 py-1 rounded",
            "text-xs font-medium tracking-wide",
            "transition-all duration-200",
            copied
              ? "bg-[oklch(0.45_0.12_145)] text-[oklch(0.9_0.05_145)]"
              : "text-[oklch(0.6_0_0)] hover:text-[oklch(0.85_0_0)] hover:bg-[oklch(0.25_0_0)]"
          )}
          title={copied ? "Copied!" : "Copy code"}
        >
          {copied ? (
            <>
              <Check className="w-3.5 h-3.5" />
              <span>Copied</span>
            </>
          ) : (
            <>
              <Copy className="w-3.5 h-3.5" />
              <span className="hidden sm:inline">Copy</span>
            </>
          )}
        </button>
      </div>

      {/* Code content with line numbers */}
      <div
        className="overflow-auto"
        style={{ maxHeight }}
      >
        <div className="flex">
          {showLineNumbers && (
            <div
              className={cn(
                "flex-shrink-0 py-3 px-3 select-none text-right",
                "bg-[oklch(0.14_0_0)] dark:bg-[oklch(0.09_0_0)]",
                "border-r border-[oklch(0.22_0_0)] dark:border-[oklch(0.16_0_0)]",
                "text-[oklch(0.45_0_0)] text-xs leading-relaxed"
              )}
            >
              {lines.map((_, i) => (
                <div key={i} className="h-[1.5rem]">
                  {i + 1}
                </div>
              ))}
            </div>
          )}

          <pre
            className={cn(
              "flex-1 py-3 px-4 overflow-x-auto m-0",
              "leading-relaxed"
            )}
          >
            <code
              ref={codeRef}
              className={`language-${detectedLang}`}
              style={{
                background: "transparent",
                padding: 0,
                margin: 0,
                lineHeight: "1.5rem",
              }}
            >
              {code}
            </code>
          </pre>
        </div>
      </div>

      {/* Subtle scan-line overlay for terminal feel */}
      <div
        className="pointer-events-none absolute inset-0 opacity-[0.015]"
        style={{
          backgroundImage: `repeating-linear-gradient(
            0deg,
            transparent,
            transparent 1px,
            oklch(1 0 0) 1px,
            oklch(1 0 0) 2px
          )`,
        }}
      />
    </div>
  );
}
