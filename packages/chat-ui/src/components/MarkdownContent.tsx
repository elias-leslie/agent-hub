import { useMemo, useCallback, useState } from "react";
import { Markdown } from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Components } from "react-markdown";
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
    <div className="relative group/code my-3 rounded-md overflow-hidden bg-black/30 border border-white/10">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-1.5 bg-white/5 border-b border-white/10 text-xs text-white/40">
        <span className="uppercase tracking-wider">{language || "code"}</span>
        <button
          onClick={handleCopy}
          className={cn(
            "flex items-center gap-1 px-1.5 py-0.5 rounded transition-colors",
            copied
              ? "text-green-400"
              : "text-white/40 hover:text-white/70",
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
      <pre className="overflow-x-auto p-3 m-0 text-sm leading-relaxed">
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
              className="px-1.5 py-0.5 rounded bg-white/10 text-[0.9em] font-mono"
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
            className="text-blue-400 hover:text-blue-300 underline underline-offset-2"
            {...rest}
          >
            {children}
          </a>
        );
      },

      // Headers
      h1({ children, ...rest }) {
        return (
          <h1 className="text-xl font-bold mt-4 mb-2" {...rest}>
            {children}
          </h1>
        );
      },
      h2({ children, ...rest }) {
        return (
          <h2 className="text-lg font-bold mt-3 mb-2" {...rest}>
            {children}
          </h2>
        );
      },
      h3({ children, ...rest }) {
        return (
          <h3 className="text-base font-bold mt-3 mb-1" {...rest}>
            {children}
          </h3>
        );
      },

      // Lists
      ul({ children, ...rest }) {
        return (
          <ul className="list-disc list-inside my-2 space-y-0.5" {...rest}>
            {children}
          </ul>
        );
      },
      ol({ children, ...rest }) {
        return (
          <ol className="list-decimal list-inside my-2 space-y-0.5" {...rest}>
            {children}
          </ol>
        );
      },
      li({ children, ...rest }) {
        return (
          <li className="leading-relaxed" {...rest}>
            {children}
          </li>
        );
      },

      // Blockquotes
      blockquote({ children, ...rest }) {
        return (
          <blockquote
            className="border-l-2 border-white/30 pl-3 my-2 italic opacity-80"
            {...rest}
          >
            {children}
          </blockquote>
        );
      },

      // Paragraphs — avoid extra margin on first/last
      p({ children, ...rest }) {
        return (
          <p className="my-1.5 leading-relaxed" {...rest}>
            {children}
          </p>
        );
      },

      // Tables (GFM)
      table({ children, ...rest }) {
        return (
          <div className="overflow-x-auto my-3">
            <table
              className="min-w-full text-sm border-collapse border border-white/20"
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
            className="border border-white/20 px-3 py-1.5 text-left font-semibold bg-white/5"
            {...rest}
          >
            {children}
          </th>
        );
      },
      td({ children, ...rest }) {
        return (
          <td className="border border-white/20 px-3 py-1.5" {...rest}>
            {children}
          </td>
        );
      },

      // Horizontal rules
      hr(rest) {
        return <hr className="border-white/20 my-4" {...rest} />;
      },

      // Strong / em
      strong({ children, ...rest }) {
        return (
          <strong className="font-bold" {...rest}>
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
    <div className={cn("markdown-content break-words", className)}>
      <Markdown remarkPlugins={remarkPlugins} components={components}>
        {content}
      </Markdown>
    </div>
  );
}
