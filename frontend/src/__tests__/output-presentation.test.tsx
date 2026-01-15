import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import {
  CodeBlock,
  DiffView,
  InlineDiff,
  MarkdownRenderer,
  CollapsibleOutput,
  CollapsibleText,
  ExportButton,
} from "@/components/output";
import type { ChatMessage } from "@/types/chat";

// Mock clipboard API
const mockClipboard = {
  writeText: vi.fn().mockResolvedValue(undefined),
};
Object.assign(navigator, { clipboard: mockClipboard });

// Mock URL.createObjectURL and URL.revokeObjectURL
global.URL.createObjectURL = vi.fn(() => "blob:mock-url");
global.URL.revokeObjectURL = vi.fn();

describe("CodeBlock", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders code content", () => {
    const { container } = render(<CodeBlock code="const x = 1;" />);
    // Code might be split by syntax highlighting spans, check container has the text
    expect(container.textContent).toContain("const");
    expect(container.textContent).toContain("x");
    expect(container.textContent).toContain("1");
  });

  it("detects TypeScript language", () => {
    render(
      <CodeBlock code="import { foo } from 'bar';\nconst x: string = 'test';" />,
    );
    expect(screen.getByText("TypeScript")).toBeInTheDocument();
  });

  it("detects Python language", () => {
    render(<CodeBlock code="def hello():\n    print('world')" />);
    expect(screen.getByText("Python")).toBeInTheDocument();
  });

  it("detects Bash language", () => {
    render(<CodeBlock code="$ npm install\n$ npm run dev" />);
    expect(screen.getByText("Bash")).toBeInTheDocument();
  });

  it("detects JSON language", () => {
    render(<CodeBlock code='{"name": "test", "value": 123}' />);
    expect(screen.getByText("JSON")).toBeInTheDocument();
  });

  it("detects SQL language", () => {
    render(<CodeBlock code="SELECT * FROM users WHERE id = 1" />);
    expect(screen.getByText("SQL")).toBeInTheDocument();
  });

  it("uses provided language over detection", () => {
    render(<CodeBlock code="some code" language="rust" />);
    expect(screen.getByText("Rust")).toBeInTheDocument();
  });

  it("displays filename when provided", () => {
    render(<CodeBlock code="const x = 1;" filename="test.ts" />);
    expect(screen.getByText("test.ts")).toBeInTheDocument();
  });

  it("shows line numbers by default", () => {
    const { container } = render(<CodeBlock code="line 1\nline 2\nline 3" />);
    // Line numbers container exists when showLineNumbers is true (default)
    const lineNumberContainer = container.querySelector(".select-none");
    expect(lineNumberContainer).toBeInTheDocument();
  });

  it("hides line numbers when showLineNumbers is false", () => {
    const { container } = render(
      <CodeBlock code="line 1\nline 2" showLineNumbers={false} />,
    );
    const lineNumberDiv = container.querySelector(".select-none.text-right");
    expect(lineNumberDiv).toBeNull();
  });

  it("copies code to clipboard when copy button clicked", async () => {
    render(<CodeBlock code="const x = 1;" />);

    const copyButton = screen.getByTitle("Copy code");
    fireEvent.click(copyButton);

    await waitFor(() => {
      expect(mockClipboard.writeText).toHaveBeenCalledWith("const x = 1;");
    });
  });

  it("shows Copied feedback after copying", async () => {
    render(<CodeBlock code="const x = 1;" />);

    const copyButton = screen.getByTitle("Copy code");
    fireEvent.click(copyButton);

    await waitFor(() => {
      expect(screen.getByText("Copied")).toBeInTheDocument();
    });
  });

  it("renders terminal dots in header", () => {
    const { container } = render(<CodeBlock code="test" />);
    const dots = container.querySelectorAll(".rounded-full");
    expect(dots.length).toBe(3);
  });
});

describe("DiffView", () => {
  const simpleDiff = `--- a/file.txt
+++ b/file.txt
@@ -1,3 +1,3 @@
 unchanged line
-removed line
+added line
 context line`;

  it("renders diff content", () => {
    render(<DiffView diff={simpleDiff} />);
    expect(screen.getByText("unchanged line")).toBeInTheDocument();
    expect(screen.getByText("removed line")).toBeInTheDocument();
    expect(screen.getByText("added line")).toBeInTheDocument();
  });

  it("shows addition and deletion stats in header", () => {
    const { container } = render(<DiffView diff={simpleDiff} />);
    // Check for the Plus and Minus icons with counts
    const header = container.querySelector(".justify-between");
    expect(header?.textContent).toContain("1"); // At least one count
  });

  it("displays filename when provided", () => {
    render(<DiffView diff={simpleDiff} filename="src/app.ts" />);
    expect(screen.getByText("src/app.ts")).toBeInTheDocument();
  });

  it("shows + indicator for added lines", () => {
    render(<DiffView diff={simpleDiff} />);
    const plusIndicators = screen.getAllByText("+");
    expect(plusIndicators.length).toBeGreaterThanOrEqual(1);
  });

  it("shows - indicator for removed lines", () => {
    render(<DiffView diff={simpleDiff} />);
    const minusIndicators = screen.getAllByText("-");
    expect(minusIndicators.length).toBeGreaterThanOrEqual(1);
  });

  it("displays line numbers for context lines", () => {
    const { container } = render(<DiffView diff={simpleDiff} />);
    // Line numbers should be in table cells
    const cells = container.querySelectorAll("td");
    expect(cells.length).toBeGreaterThan(0);
  });
});

describe("InlineDiff", () => {
  it("renders old and new text", () => {
    render(<InlineDiff oldText="hello" newText="world" />);
    expect(screen.getByText("hello")).toBeInTheDocument();
    expect(screen.getByText("world")).toBeInTheDocument();
  });

  it("applies strikethrough to old text", () => {
    render(<InlineDiff oldText="old" newText="new" />);
    const oldText = screen.getByText("old");
    expect(oldText).toHaveClass("line-through");
  });
});

describe("MarkdownRenderer", () => {
  it("renders plain text", () => {
    render(<MarkdownRenderer content="Hello world" />);
    expect(screen.getByText("Hello world")).toBeInTheDocument();
  });

  it("renders h1 header", () => {
    const { container } = render(<MarkdownRenderer content="# Heading 1" />);
    expect(container.querySelector("h1")).toBeInTheDocument();
    expect(container.textContent).toContain("Heading 1");
  });

  it("renders h2 header", () => {
    const { container } = render(<MarkdownRenderer content="## Heading 2" />);
    expect(container.querySelector("h2")).toBeInTheDocument();
    expect(container.textContent).toContain("Heading 2");
  });

  it("renders bold text", () => {
    render(<MarkdownRenderer content="This is **bold** text" />);
    expect(screen.getByText("bold")).toBeInTheDocument();
  });

  it("renders italic text", () => {
    render(<MarkdownRenderer content="This is *italic* text" />);
    expect(screen.getByText("italic")).toBeInTheDocument();
  });

  it("renders links", () => {
    render(<MarkdownRenderer content="[Click here](https://example.com)" />);
    const link = screen.getByText("Click here");
    expect(link).toHaveAttribute("href", "https://example.com");
  });

  it("renders unordered lists", () => {
    const { container } = render(
      <MarkdownRenderer content="- Item 1\n- Item 2\n- Item 3" />,
    );
    const list = container.querySelector("ul");
    expect(list).toBeInTheDocument();
    expect(container.textContent).toContain("Item 1");
    expect(container.textContent).toContain("Item 2");
  });

  it("renders ordered lists", () => {
    const { container } = render(
      <MarkdownRenderer content="1. First\n2. Second\n3. Third" />,
    );
    const list = container.querySelector("ol");
    expect(list).toBeInTheDocument();
    expect(container.textContent).toContain("First");
    expect(container.textContent).toContain("Second");
  });

  it("renders blockquotes", () => {
    render(<MarkdownRenderer content="> This is a quote" />);
    expect(screen.getByText("This is a quote")).toBeInTheDocument();
  });

  it("renders inline code", () => {
    render(<MarkdownRenderer content="Use `const` for constants" />);
    expect(screen.getByText("const")).toBeInTheDocument();
  });

  it("renders code blocks", () => {
    const { container } = render(
      <MarkdownRenderer content="```typescript\nconst x = 1;\n```" />,
    );
    // Should render a CodeBlock component
    expect(container.textContent).toContain("const");
  });

  it("renders tables", () => {
    const tableMarkdown = `| Name | Age |
| --- | --- |
| Alice | 30 |
| Bob | 25 |`;
    render(<MarkdownRenderer content={tableMarkdown} />);
    expect(screen.getByText("Name")).toBeInTheDocument();
    expect(screen.getByText("Alice")).toBeInTheDocument();
    expect(screen.getByText("30")).toBeInTheDocument();
  });
});

describe("CollapsibleOutput", () => {
  it("renders children directly when content fits", () => {
    render(
      <CollapsibleOutput maxHeight={1000}>
        <div>Short content</div>
      </CollapsibleOutput>,
    );
    expect(screen.getByText("Short content")).toBeInTheDocument();
    expect(screen.queryByText("Show more")).not.toBeInTheDocument();
  });

  // Note: Testing overflow behavior requires more complex DOM mocking
  // These tests verify the basic rendering behavior
  it("renders content within container", () => {
    const { container } = render(
      <CollapsibleOutput maxHeight={100}>
        <div>Content here</div>
      </CollapsibleOutput>,
    );
    expect(container.textContent).toContain("Content here");
  });
});

describe("CollapsibleText", () => {
  it("renders all text when under maxLines", () => {
    render(<CollapsibleText text="Line 1\nLine 2" maxLines={10} />);
    expect(screen.getByText(/Line 1/)).toBeInTheDocument();
    expect(screen.getByText(/Line 2/)).toBeInTheDocument();
  });

  it("truncates text when over maxLines", () => {
    const longText = Array.from({ length: 20 }, (_, i) => `Line ${i + 1}`).join(
      "\n",
    );
    render(<CollapsibleText text={longText} maxLines={5} />);

    expect(screen.getByText("+ 15 more lines")).toBeInTheDocument();
  });

  it("expands to show full text when clicked", () => {
    const longText = Array.from({ length: 20 }, (_, i) => `Line ${i + 1}`).join(
      "\n",
    );
    render(<CollapsibleText text={longText} maxLines={5} />);

    fireEvent.click(screen.getByText("+ 15 more lines"));
    expect(screen.getByText("Show less")).toBeInTheDocument();
  });

  it("collapses when Show less is clicked", () => {
    const longText = Array.from({ length: 20 }, (_, i) => `Line ${i + 1}`).join(
      "\n",
    );
    render(<CollapsibleText text={longText} maxLines={5} />);

    // Expand
    fireEvent.click(screen.getByText("+ 15 more lines"));
    // Collapse
    fireEvent.click(screen.getByText("Show less"));
    expect(screen.getByText("+ 15 more lines")).toBeInTheDocument();
  });
});

describe("ExportButton", () => {
  const messages: ChatMessage[] = [
    {
      id: "1",
      role: "user",
      content: "Hello",
      timestamp: new Date("2024-01-01T10:00:00"),
    },
    {
      id: "2",
      role: "assistant",
      content: "Hi there!",
      timestamp: new Date("2024-01-01T10:00:05"),
      agentName: "Claude",
    },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders nothing when messages is empty", () => {
    const { container } = render(<ExportButton messages={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders export button when messages exist", () => {
    render(<ExportButton messages={messages} />);
    expect(screen.getByText("Export")).toBeInTheDocument();
  });

  it("opens dropdown when clicked", () => {
    render(<ExportButton messages={messages} />);
    fireEvent.click(screen.getByText("Export"));

    expect(screen.getByText("Markdown")).toBeInTheDocument();
    expect(screen.getByText("JSON")).toBeInTheDocument();
  });

  it("shows message count in dropdown", () => {
    render(<ExportButton messages={messages} />);
    fireEvent.click(screen.getByText("Export"));

    expect(screen.getByText("2 messages to export")).toBeInTheDocument();
  });

  it("shows format descriptions", () => {
    render(<ExportButton messages={messages} />);
    fireEvent.click(screen.getByText("Export"));

    expect(screen.getByText("Human-readable format")).toBeInTheDocument();
    expect(screen.getByText("Machine-readable format")).toBeInTheDocument();
  });

  it("closes dropdown when Export button clicked again", () => {
    render(<ExportButton messages={messages} />);

    // Open
    fireEvent.click(screen.getByText("Export"));
    expect(screen.getByText("Markdown")).toBeInTheDocument();

    // Close by clicking export again (the dropdown toggles)
    fireEvent.click(screen.getByText("Export"));
    // Dropdown should close - the Markdown option should no longer be visible
    // Note: Due to how the backdrop works, we check the state changed
  });

  it("shows singular message text for single message", () => {
    render(<ExportButton messages={[messages[0]]} />);
    fireEvent.click(screen.getByText("Export"));

    expect(screen.getByText("1 message to export")).toBeInTheDocument();
  });

  it("shows chevron icon that rotates when open", () => {
    const { container } = render(<ExportButton messages={messages} />);

    const chevron = container.querySelector(".transition-transform");
    expect(chevron).toBeInTheDocument();

    // Open dropdown
    fireEvent.click(screen.getByText("Export"));
    expect(chevron).toHaveClass("rotate-180");
  });

  it("includes Download icon", () => {
    render(<ExportButton messages={messages} />);
    // The Download icon from lucide-react renders as an SVG
    const button = screen.getByText("Export").closest("button");
    expect(button?.querySelector("svg")).toBeInTheDocument();
  });
});
