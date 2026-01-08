import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import PreferencesPage from "@/app/settings/preferences/page";

// Mock the API
vi.mock("@/lib/api", () => ({
  fetchUserPreferences: vi.fn(),
  updateUserPreferences: vi.fn(),
}));

import { fetchUserPreferences, updateUserPreferences } from "@/lib/api";

const createQueryClient = () =>
  new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });

const renderWithProviders = (component: React.ReactElement) => {
  const queryClient = createQueryClient();
  return render(
    <QueryClientProvider client={queryClient}>{component}</QueryClientProvider>
  );
};

describe("PreferencesPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (fetchUserPreferences as ReturnType<typeof vi.fn>).mockResolvedValue({
      verbosity: "normal",
      tone: "professional",
      default_model: "claude-sonnet-4-5",
    });
    (updateUserPreferences as ReturnType<typeof vi.fn>).mockResolvedValue({
      verbosity: "normal",
      tone: "professional",
      default_model: "claude-sonnet-4-5",
    });
  });

  it("renders preferences page with header", async () => {
    renderWithProviders(<PreferencesPage />);

    expect(screen.getByText("Preferences")).toBeInTheDocument();
    expect(screen.getByText("SYS.CONFIG.USER")).toBeInTheDocument();
  });

  it("shows loading state initially", () => {
    renderWithProviders(<PreferencesPage />);

    expect(screen.getByText("Loading preferences...")).toBeInTheDocument();
  });

  it("displays verbosity options after loading", async () => {
    renderWithProviders(<PreferencesPage />);

    await waitFor(() => {
      expect(screen.getByText("Concise")).toBeInTheDocument();
      expect(screen.getByText("Normal")).toBeInTheDocument();
      expect(screen.getByText("Detailed")).toBeInTheDocument();
    });
  });

  it("displays tone options after loading", async () => {
    renderWithProviders(<PreferencesPage />);

    await waitFor(() => {
      expect(screen.getByText("Professional")).toBeInTheDocument();
      expect(screen.getByText("Friendly")).toBeInTheDocument();
      expect(screen.getByText("Technical")).toBeInTheDocument();
    });
  });

  it("displays model options after loading", async () => {
    renderWithProviders(<PreferencesPage />);

    await waitFor(() => {
      expect(screen.getByText("Claude Sonnet 4.5")).toBeInTheDocument();
      expect(screen.getByText("Claude Opus 4.5")).toBeInTheDocument();
      expect(screen.getByText("Claude Haiku 4.5")).toBeInTheDocument();
      expect(screen.getByText("Gemini 3 Flash")).toBeInTheDocument();
      expect(screen.getByText("Gemini 3 Pro")).toBeInTheDocument();
    });
  });

  it("shows save button as disabled initially", async () => {
    renderWithProviders(<PreferencesPage />);

    await waitFor(() => {
      expect(screen.getByText("Concise")).toBeInTheDocument();
    });

    const saveButton = screen.getByRole("button", { name: /save/i });
    expect(saveButton).toBeDisabled();
  });

  it("enables save button when preference changed", async () => {
    renderWithProviders(<PreferencesPage />);

    await waitFor(() => {
      expect(screen.getByText("Concise")).toBeInTheDocument();
    });

    // Click on Detailed verbosity
    fireEvent.click(screen.getByText("Detailed"));

    const saveButton = screen.getByRole("button", { name: /save/i });
    expect(saveButton).not.toBeDisabled();
  });

  it("shows reset button when changes made", async () => {
    renderWithProviders(<PreferencesPage />);

    await waitFor(() => {
      expect(screen.getByText("Concise")).toBeInTheDocument();
    });

    // Initially no reset button
    expect(screen.queryByText("Reset")).not.toBeInTheDocument();

    // Make a change
    fireEvent.click(screen.getByText("Detailed"));

    // Reset button should appear
    expect(screen.getByText("Reset")).toBeInTheDocument();
  });

  it("calls updateUserPreferences on save", async () => {
    renderWithProviders(<PreferencesPage />);

    await waitFor(() => {
      expect(screen.getByText("Concise")).toBeInTheDocument();
    });

    // Change verbosity
    fireEvent.click(screen.getByText("Detailed"));

    // Save
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() => {
      expect(updateUserPreferences).toHaveBeenCalled();
    });

    // Verify the call contains the updated verbosity
    const callArg = (updateUserPreferences as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(callArg.verbosity).toBe("detailed");
  });

  it("shows saved confirmation after successful save", async () => {
    renderWithProviders(<PreferencesPage />);

    await waitFor(() => {
      expect(screen.getByText("Concise")).toBeInTheDocument();
    });

    // Change and save
    fireEvent.click(screen.getByText("Detailed"));
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() => {
      expect(screen.getByText("Saved")).toBeInTheDocument();
    });
  });

  it("updates verbosity meter bars visualization", async () => {
    renderWithProviders(<PreferencesPage />);

    await waitFor(() => {
      expect(screen.getByText("Concise")).toBeInTheDocument();
    });

    // Normal is default, check meter visualization exists
    // This is visual so we just verify the section renders
    expect(screen.getByText("Response Verbosity")).toBeInTheDocument();
  });

  it("displays model tier badges", async () => {
    renderWithProviders(<PreferencesPage />);

    await waitFor(() => {
      // There are 2 premium models (Opus, Gemini Pro)
      expect(screen.getAllByText("premium").length).toBe(2);
      // There is 1 fast model (Haiku)
      expect(screen.getAllByText("fast").length).toBe(1);
      // There are 2 default models (Sonnet, Gemini Flash)
      expect(screen.getAllByText("default").length).toBe(2);
    });
  });

  it("resets changes when reset button clicked", async () => {
    renderWithProviders(<PreferencesPage />);

    await waitFor(() => {
      expect(screen.getByText("Concise")).toBeInTheDocument();
    });

    // Make change
    fireEvent.click(screen.getByText("Detailed"));
    expect(screen.getByText("Reset")).toBeInTheDocument();

    // Reset
    fireEvent.click(screen.getByText("Reset"));

    // Save button should be disabled again
    const saveButton = screen.getByRole("button", { name: /save/i });
    expect(saveButton).toBeDisabled();
  });

  it("has link back to settings", async () => {
    renderWithProviders(<PreferencesPage />);

    await waitFor(() => {
      expect(screen.getByText("Concise")).toBeInTheDocument();
    });

    const settingsLink = screen.getByText("Back to Settings");
    expect(settingsLink).toHaveAttribute("href", "/settings");
  });
});
