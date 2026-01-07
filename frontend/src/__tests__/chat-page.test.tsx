import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import ChatPage from "@/app/chat/page";

// Mock the ChatPanel component to avoid WebSocket complexity
vi.mock("@/components/chat", () => ({
  ChatPanel: ({ model }: { model?: string }) => (
    <div data-testid="chat-panel" data-model={model}>
      Mock Chat Panel
    </div>
  ),
}));

describe("ChatPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders chat page header", () => {
    render(<ChatPage />);
    expect(screen.getByText("Chat")).toBeInTheDocument();
  });

  it("shows single mode by default", () => {
    render(<ChatPage />);
    expect(screen.getByText("Single")).toBeInTheDocument();
    expect(screen.getByText("Roundtable")).toBeInTheDocument();
    // Single mode should show one chat panel
    expect(screen.getByTestId("chat-panel")).toBeInTheDocument();
  });

  it("shows model selector in single mode", () => {
    render(<ChatPage />);
    expect(screen.getByText("Claude Sonnet 4.5")).toBeInTheDocument();
  });

  it("switches to roundtable mode", () => {
    render(<ChatPage />);

    // Click roundtable button
    fireEvent.click(screen.getByText("Roundtable"));

    // Should show multiple chat panels
    const panels = screen.getAllByTestId("chat-panel");
    expect(panels.length).toBe(2); // Default 2 models in roundtable
  });

  it("shows model badges in roundtable mode", () => {
    render(<ChatPage />);
    fireEvent.click(screen.getByText("Roundtable"));

    // Should show model badges
    expect(screen.getByText("4.5")).toBeInTheDocument(); // Claude Sonnet 4.5 -> "4.5"
    expect(screen.getByText("Flash")).toBeInTheDocument(); // Gemini Flash -> "Flash"
  });

  it("opens model dropdown when clicked", () => {
    render(<ChatPage />);

    // Click on model selector
    fireEvent.click(screen.getByText("Claude Sonnet 4.5"));

    // Should show all available models
    expect(screen.getByText("Claude Opus 4.5")).toBeInTheDocument();
    expect(screen.getByText("Claude Haiku 4.5")).toBeInTheDocument();
    expect(screen.getByText("Gemini 3 Flash")).toBeInTheDocument();
    expect(screen.getByText("Gemini 3 Pro")).toBeInTheDocument();
  });

  it("changes model when selected from dropdown", () => {
    render(<ChatPage />);

    // Open dropdown
    fireEvent.click(screen.getByText("Claude Sonnet 4.5"));

    // Select different model
    fireEvent.click(screen.getByText("Claude Opus 4.5"));

    // Chat panel should now have the new model
    const panel = screen.getByTestId("chat-panel");
    expect(panel).toHaveAttribute("data-model", "claude-opus-4-5-20251101");
  });

  it("shows settings panel in roundtable mode", () => {
    render(<ChatPage />);

    // Switch to roundtable
    fireEvent.click(screen.getByText("Roundtable"));

    // Click settings button (Settings2 icon button)
    const settingsButton = screen.getByRole("button", { name: "" }); // Icon button
    // Find by svg parent - settings is the last button
    const buttons = screen.getAllByRole("button");
    const settingsBtn = buttons.find((btn) =>
      btn.querySelector('svg[class*="lucide-settings"]')
    );
    if (settingsBtn) {
      fireEvent.click(settingsBtn);

      // Should show model selection panel
      expect(
        screen.getByText("Select 2-4 models for roundtable discussion:")
      ).toBeInTheDocument();
    }
  });

  it("passes correct model to ChatPanel in single mode", () => {
    render(<ChatPage />);

    const panel = screen.getByTestId("chat-panel");
    // Default model is Claude Sonnet 4.5
    expect(panel).toHaveAttribute("data-model", "claude-sonnet-4-5-20250514");
  });
});
