import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import SettingsPage from "@/app/settings/page";

// Mock the API module
vi.mock("@/lib/api", () => ({
  fetchCredentials: vi.fn(),
  createCredential: vi.fn(),
  updateCredential: vi.fn(),
  deleteCredential: vi.fn(),
}));

import {
  fetchCredentials,
  createCredential,
  updateCredential,
} from "@/lib/api";

const mockCredentials = {
  credentials: [
    {
      id: 1,
      provider: "claude",
      credential_type: "api_key",
      value_masked: "sk-a****key1",
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-02T00:00:00Z",
    },
    {
      id: 2,
      provider: "gemini",
      credential_type: "api_key",
      value_masked: "AIza****key2",
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-03T00:00:00Z",
    },
  ],
  total: 2,
};

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
  };
}

describe("SettingsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchCredentials).mockResolvedValue(mockCredentials);
  });

  it("renders settings page header", async () => {
    render(<SettingsPage />, { wrapper: createWrapper() });

    expect(screen.getByText("Settings")).toBeInTheDocument();
    expect(
      screen.getByText("Manage credentials and preferences"),
    ).toBeInTheDocument();
  });

  it("displays credentials section", async () => {
    render(<SettingsPage />, { wrapper: createWrapper() });

    expect(screen.getByText("Provider Credentials")).toBeInTheDocument();
    expect(screen.getByText("Add Credential")).toBeInTheDocument();
  });

  it("shows credentials after loading", async () => {
    render(<SettingsPage />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText("Claude (Anthropic)")).toBeInTheDocument();
      expect(screen.getByText("Gemini (Google)")).toBeInTheDocument();
    });
  });

  it("shows add credential form when button clicked", async () => {
    render(<SettingsPage />, { wrapper: createWrapper() });

    fireEvent.click(screen.getByText("Add Credential"));

    expect(screen.getByText("Add New Credential")).toBeInTheDocument();
    expect(screen.getByText("Save Credential")).toBeInTheDocument();
  });

  it("hides add form when Cancel clicked", async () => {
    render(<SettingsPage />, { wrapper: createWrapper() });

    // Open form
    fireEvent.click(screen.getByText("Add Credential"));
    expect(screen.getByText("Add New Credential")).toBeInTheDocument();

    // Close form
    fireEvent.click(screen.getByText("Cancel"));
    expect(screen.queryByText("Add New Credential")).not.toBeInTheDocument();
  });

  it("creates credential when form submitted", async () => {
    vi.mocked(createCredential).mockResolvedValue({
      id: 3,
      provider: "claude",
      credential_type: "api_key",
      value_masked: "sk-n****new1",
      created_at: "2026-01-07T00:00:00Z",
      updated_at: "2026-01-07T00:00:00Z",
    });

    render(<SettingsPage />, { wrapper: createWrapper() });

    // Open form
    fireEvent.click(screen.getByText("Add Credential"));

    // Fill in value
    const valueInput = screen.getByPlaceholderText("sk-...");
    fireEvent.change(valueInput, { target: { value: "sk-new-key-123" } });

    // Submit
    fireEvent.click(screen.getByText("Save Credential"));

    await waitFor(() => {
      expect(createCredential).toHaveBeenCalled();
      const [firstArg] = vi.mocked(createCredential).mock.calls[0];
      expect(firstArg).toEqual({
        provider: "claude",
        credential_type: "api_key",
        value: "sk-new-key-123",
      });
    });
  });

  it("shows edit input when edit button clicked", async () => {
    render(<SettingsPage />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText("Claude (Anthropic)")).toBeInTheDocument();
    });

    // Click edit button (first one)
    const editButtons = screen.getAllByTitle("Edit credential");
    fireEvent.click(editButtons[0]);

    // Should show edit input
    expect(
      screen.getByPlaceholderText("Enter new value..."),
    ).toBeInTheDocument();
  });

  it("updates credential when edit submitted", async () => {
    vi.mocked(updateCredential).mockResolvedValue({
      id: 1,
      provider: "claude",
      credential_type: "api_key",
      value_masked: "sk-u****upd1",
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-07T00:00:00Z",
    });

    render(<SettingsPage />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText("Claude (Anthropic)")).toBeInTheDocument();
    });

    // Click edit
    const editButtons = screen.getAllByTitle("Edit credential");
    fireEvent.click(editButtons[0]);

    // Enter new value
    const editInput = screen.getByPlaceholderText("Enter new value...");
    fireEvent.change(editInput, { target: { value: "sk-updated-key" } });

    // Submit (click check button)
    const checkButtons = screen.getAllByRole("button");
    const submitButton = checkButtons.find(
      (btn) => btn.querySelector('svg[class*="lucide-check"]') !== null,
    );
    if (submitButton) {
      fireEvent.click(submitButton);
    }

    await waitFor(() => {
      expect(updateCredential).toHaveBeenCalledWith(1, "sk-updated-key");
    });
  });

  it("shows empty state when no credentials", async () => {
    vi.mocked(fetchCredentials).mockResolvedValue({
      credentials: [],
      total: 0,
    });

    render(<SettingsPage />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText("No credentials configured")).toBeInTheDocument();
      expect(
        screen.getByText("Add your API keys to get started"),
      ).toBeInTheDocument();
    });
  });

  it("shows user preferences section", async () => {
    render(<SettingsPage />, { wrapper: createWrapper() });

    expect(screen.getByText("User Preferences")).toBeInTheDocument();
    expect(screen.getByText("Manage Preferences →")).toBeInTheDocument();
  });
});
