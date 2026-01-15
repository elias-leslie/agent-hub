"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { cn } from "@/lib/utils";
import { CodeBlock } from "./code-block";
import type { Components } from "react-markdown";

interface MarkdownRendererProps {
  content: string;
  className?: string;
}

export function MarkdownRenderer({
  content,
  className,
}: MarkdownRendererProps) {
  const components: Components = {
    // Code blocks with syntax highlighting
    code({ className: codeClassName, children, ...props }) {
      const match = /language-(\w+)/.exec(codeClassName || "");
      const isInline = !match && !String(children).includes("\n");

      if (isInline) {
        return (
          <code
            className={cn(
              "px-1.5 py-0.5 rounded font-mono text-[0.875em]",
              "bg-[oklch(0.92_0_0)] dark:bg-[oklch(0.2_0_0)]",
              "text-[oklch(0.45_0.12_320)] dark:text-[oklch(0.75_0.12_320)]",
              "border border-[oklch(0.88_0_0)] dark:border-[oklch(0.25_0_0)]",
            )}
            {...props}
          >
            {children}
          </code>
        );
      }

      return (
        <CodeBlock
          code={String(children).replace(/\n$/, "")}
          language={match?.[1]}
          className="my-4"
        />
      );
    },

    // Headers with anchor styling
    h1: ({ children }) => (
      <h1
        className={cn(
          "text-2xl font-bold mt-8 mb-4 pb-2",
          "border-b border-[oklch(0.9_0_0)] dark:border-[oklch(0.25_0_0)]",
          "text-[oklch(0.15_0_0)] dark:text-[oklch(0.95_0_0)]",
        )}
      >
        {children}
      </h1>
    ),
    h2: ({ children }) => (
      <h2
        className={cn(
          "text-xl font-bold mt-6 mb-3 pb-1.5",
          "border-b border-[oklch(0.92_0_0)] dark:border-[oklch(0.22_0_0)]",
          "text-[oklch(0.18_0_0)] dark:text-[oklch(0.92_0_0)]",
        )}
      >
        {children}
      </h2>
    ),
    h3: ({ children }) => (
      <h3
        className={cn(
          "text-lg font-semibold mt-5 mb-2",
          "text-[oklch(0.2_0_0)] dark:text-[oklch(0.9_0_0)]",
        )}
      >
        {children}
      </h3>
    ),
    h4: ({ children }) => (
      <h4
        className={cn(
          "text-base font-semibold mt-4 mb-2",
          "text-[oklch(0.25_0_0)] dark:text-[oklch(0.85_0_0)]",
        )}
      >
        {children}
      </h4>
    ),

    // Paragraphs
    p: ({ children }) => (
      <p className="my-3 leading-relaxed text-[oklch(0.3_0_0)] dark:text-[oklch(0.8_0_0)]">
        {children}
      </p>
    ),

    // Lists
    ul: ({ children }) => (
      <ul className="my-3 ml-6 space-y-1.5 list-disc marker:text-[oklch(0.5_0_0)]">
        {children}
      </ul>
    ),
    ol: ({ children }) => (
      <ol className="my-3 ml-6 space-y-1.5 list-decimal marker:text-[oklch(0.5_0_0)]">
        {children}
      </ol>
    ),
    li: ({ children }) => (
      <li className="leading-relaxed text-[oklch(0.3_0_0)] dark:text-[oklch(0.8_0_0)]">
        {children}
      </li>
    ),

    // Links
    a: ({ href, children }) => (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className={cn(
          "font-medium underline underline-offset-2 decoration-1",
          "text-[oklch(0.5_0.15_250)] dark:text-[oklch(0.7_0.15_250)]",
          "hover:text-[oklch(0.4_0.18_250)] dark:hover:text-[oklch(0.8_0.18_250)]",
          "transition-colors",
        )}
      >
        {children}
      </a>
    ),

    // Blockquotes
    blockquote: ({ children }) => (
      <blockquote
        className={cn(
          "my-4 pl-4 py-1 border-l-3",
          "border-[oklch(0.7_0.08_250)] dark:border-[oklch(0.5_0.08_250)]",
          "bg-[oklch(0.97_0.01_250)] dark:bg-[oklch(0.15_0.01_250)]",
          "rounded-r-md italic",
          "[&>p]:my-1 [&>p]:text-[oklch(0.4_0_0)] dark:[&>p]:text-[oklch(0.7_0_0)]",
        )}
      >
        {children}
      </blockquote>
    ),

    // Tables
    table: ({ children }) => (
      <div className="my-4 overflow-x-auto rounded-lg border border-[oklch(0.9_0_0)] dark:border-[oklch(0.25_0_0)]">
        <table className="w-full border-collapse text-sm">{children}</table>
      </div>
    ),
    thead: ({ children }) => (
      <thead className="bg-[oklch(0.96_0_0)] dark:bg-[oklch(0.18_0_0)]">
        {children}
      </thead>
    ),
    tbody: ({ children }) => <tbody>{children}</tbody>,
    tr: ({ children }) => (
      <tr className="border-b border-[oklch(0.92_0_0)] dark:border-[oklch(0.22_0_0)] last:border-0">
        {children}
      </tr>
    ),
    th: ({ children }) => (
      <th
        className={cn(
          "px-4 py-2 text-left font-semibold",
          "text-[oklch(0.25_0_0)] dark:text-[oklch(0.9_0_0)]",
          "border-r border-[oklch(0.92_0_0)] dark:border-[oklch(0.22_0_0)] last:border-0",
        )}
      >
        {children}
      </th>
    ),
    td: ({ children }) => (
      <td
        className={cn(
          "px-4 py-2",
          "text-[oklch(0.35_0_0)] dark:text-[oklch(0.75_0_0)]",
          "border-r border-[oklch(0.94_0_0)] dark:border-[oklch(0.2_0_0)] last:border-0",
        )}
      >
        {children}
      </td>
    ),

    // Horizontal rule
    hr: () => (
      <hr className="my-6 border-0 h-px bg-gradient-to-r from-transparent via-[oklch(0.8_0_0)] dark:via-[oklch(0.3_0_0)] to-transparent" />
    ),

    // Strong/Bold
    strong: ({ children }) => (
      <strong className="font-semibold text-[oklch(0.2_0_0)] dark:text-[oklch(0.95_0_0)]">
        {children}
      </strong>
    ),

    // Emphasis/Italic
    em: ({ children }) => (
      <em className="italic text-[oklch(0.35_0.02_0)] dark:text-[oklch(0.8_0.02_0)]">
        {children}
      </em>
    ),

    // Images
    img: ({ src, alt }) => (
      <span className="block my-4">
        {/* eslint-disable-next-line @next/next/no-img-element -- next/image doesn't support dynamic markdown sources */}
        <img
          src={src}
          alt={alt || ""}
          className={cn(
            "max-w-full h-auto rounded-lg",
            "border border-[oklch(0.9_0_0)] dark:border-[oklch(0.25_0_0)]",
            "shadow-sm",
          )}
        />
        {alt && (
          <span className="block mt-2 text-center text-sm text-[oklch(0.5_0_0)] dark:text-[oklch(0.6_0_0)]">
            {alt}
          </span>
        )}
      </span>
    ),
  };

  return (
    <div className={cn("prose-reset", className)}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  );
}
