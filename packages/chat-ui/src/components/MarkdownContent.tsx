import { useMemo, useCallback, useState } from "react";
import Markdown from "react-markdown";
import type { Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { cn } from "../lib/utils";
import { Check, Copy } from "lucide-react";

/**
 * A simple code block with copy button for fenced code in markdown.
 * Lightweight alternative to the full CodeBlock component in the frontend.
 */
function MarkdownCodeBlock({
  children,
  className,
}: { children?: React.ReactNode; className?: string }) {
  const [copied, setCopied] = useState(false);
  const code = String(children).replace(/\n$/, "");
  const langMatch = className?.match(/language-(\w+)/);
  const language = langMatch?.[1] ?? "";

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(code);
    } catch {
      const textarea = document.createElement("textarea");
      textarea.value = code;
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand("copy");
      document.body.removeChild(textarea);
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [code]);

  return (
    <div className="relative group/code my-3 overflow-hidden rounded-md border border-border bg-muted/45">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border bg-muted/60 px-3 py-1.5 text-xs text-muted-foreground">
        <span className="font-medium uppercase tracking-[0.14em]">{language || "code"}</span>
        <button
          onClick={handleCopy}
          className={cn(
            "flex items-center gap-1 px-1.5 py-0.5 rounded transition-colors",
            copied
              ? "text-emerald-500"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {copied ? (
            <>
              <Check className="w-3 h-3" />
              <span>Copied</span>
            </>
          ) : (
            <>
              <Copy className="w-3 h-3" />
              <span>Copy</span>
            </>
          )}
        </button>
      </div>
      {/* Code content */}
      <pre className="m-0 overflow-x-auto p-3 text-sm leading-6 text-foreground">
        <code className={className}>{code}</code>
      </pre>
    </div>
  );
}

const remarkPlugins = [remarkGfm];

interface MarkdownContentProps {
  content: string;
  className?: string;
}

/**
 * Renders markdown content for assistant messages.
 * Supports bold, italic, links, inline code, code blocks, lists, headers, tables (via GFM).
 */
export function MarkdownContent({ content, className }: MarkdownContentProps) {
  const components = useMemo<Components>(
    () => ({
      // Code blocks (fenced) vs inline code
      code({ className: codeClassName, children, ...rest }) {
        // react-markdown v10: fenced code blocks are wrapped in <pre><code>
        // Inline code gets no className, and is NOT inside <pre>
        const isInline = !codeClassName;
        if (isInline) {
          return (
            <code
              className="rounded bg-muted px-1.5 py-0.5 font-mono text-[0.9em] text-foreground"
              {...rest}
            >
              {children}
            </code>
          );
        }
        // Fenced code block — handled by the pre override
        return (
          <code className={codeClassName} {...rest}>
            {children}
          </code>
        );
      },

      // Fenced code blocks are <pre><code>
      pre({ children }) {
        // children is a <code> element — extract props
        const codeChild = children as React.ReactElement<{
          className?: string;
          children?: React.ReactNode;
        }>;
        if (codeChild?.props) {
          return (
            <MarkdownCodeBlock className={codeChild.props.className}>
              {codeChild.props.children}
            </MarkdownCodeBlock>
          );
        }
        return <pre className="overflow-x-auto">{children}</pre>;
      },

      // Links open in new tab
      a({ href, children, ...rest }) {
        return (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="text-amber-500 underline underline-offset-2 transition hover:text-amber-400"
            {...rest}
          >
            {children}
          </a>
        );
      },

      // Headers
      h1({ children, ...rest }) {
        return (
          <h1 className="mb-2 mt-5 text-xl font-semibold tracking-tight" {...rest}>
            {children}
          </h1>
        );
      },
      h2({ children, ...rest }) {
        return (
          <h2 className="mb-2 mt-4 text-lg font-semibold tracking-tight" {...rest}>
            {children}
          </h2>
        );
      },
      h3({ children, ...rest }) {
        return (
          <h3 className="mb-1.5 mt-3 text-base font-semibold" {...rest}>
            {children}
          </h3>
        );
      },

      // Lists
      ul({ children, ...rest }) {
        return (
          <ul className="my-2 list-outside list-disc space-y-1 pl-5 marker:text-muted-foreground" {...rest}>
            {children}
          </ul>
        );
      },
      ol({ children, ...rest }) {
        return (
          <ol className="my-2 list-outside list-decimal space-y-1 pl-5 marker:text-muted-foreground marker:font-medium" {...rest}>
            {children}
          </ol>
        );
      },
      li({ children, ...rest }) {
        return (
          <li className="pl-1 leading-6" {...rest}>
            {children}
          </li>
        );
      },

      // Blockquotes
      blockquote({ children, ...rest }) {
        return (
          <blockquote
            className="my-3 border-l-2 border-amber-500/50 pl-3 text-muted-foreground"
            {...rest}
          >
            {children}
          </blockquote>
        );
      },

      // Paragraphs — avoid extra margin on first/last
      p({ children, ...rest }) {
        return (
          <p className="my-2 leading-6" {...rest}>
            {children}
          </p>
        );
      },

      // Tables (GFM)
      table({ children, ...rest }) {
        return (
          <div className="my-3 overflow-x-auto rounded-md border border-border">
            <table
              className="min-w-full border-collapse text-sm"
              {...rest}
            >
              {children}
            </table>
          </div>
        );
      },
      th({ children, ...rest }) {
        return (
          <th
            className="border-b border-border bg-muted/60 px-3 py-2 text-left font-semibold"
            {...rest}
          >
            {children}
          </th>
        );
      },
      td({ children, ...rest }) {
        return (
          <td className="border-b border-border px-3 py-2 align-top" {...rest}>
            {children}
          </td>
        );
      },

      // Horizontal rules
      hr(rest) {
        return <hr className="my-4 border-border" {...rest} />;
      },

      // Strong / em
      strong({ children, ...rest }) {
        return (
          <strong className="font-semibold" {...rest}>
            {children}
          </strong>
        );
      },
      em({ children, ...rest }) {
        return (
          <em className="italic" {...rest}>
            {children}
          </em>
        );
      },
    }),
    [],
  );

  return (
    <div className={cn("markdown-content max-w-none break-words text-sm leading-6 text-foreground", className)}>
      <Markdown remarkPlugins={remarkPlugins} components={components}>
        {content}
      </Markdown>
    </div>
  );
}
