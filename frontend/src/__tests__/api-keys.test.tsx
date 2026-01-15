import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import APIKeysPage from "@/app/settings/api-keys/page";

// Mock the API module
vi.mock("@/lib/api", () => ({
  fetchAPIKeys: vi.fn(),
  createAPIKey: vi.fn(),
  revokeAPIKey: vi.fn(),
  deleteAPIKey: vi.fn(),
}));

import * as api from "@/lib/api";

const mockFetchAPIKeys = vi.mocked(api.fetchAPIKeys);
const mockCreateAPIKey = vi.mocked(api.createAPIKey);
const _mockRevokeAPIKey = vi.mocked(api.revokeAPIKey);

// Helper to create QueryClient wrapper
function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
  };
}

describe("API Keys Page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders loading state initially", () => {
    mockFetchAPIKeys.mockImplementation(() => new Promise(() => {}));
    render(<APIKeysPage />, { wrapper: createWrapper() });

    expect(screen.getByText(/loading api keys/i)).toBeInTheDocument();
  });

  it("displays API keys page header", async () => {
    mockFetchAPIKeys.mockResolvedValue({ keys: [], total: 0 });
    render(<APIKeysPage />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(
        screen.getByRole("heading", { name: /api keys/i }),
      ).toBeInTheDocument();
    });
  });

  it("shows empty state when no keys exist", async () => {
    mockFetchAPIKeys.mockResolvedValue({ keys: [], total: 0 });
    render(<APIKeysPage />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText(/no api keys/i)).toBeInTheDocument();
    });
  });

  it("displays list of API keys", async () => {
    mockFetchAPIKeys.mockResolvedValue({
      keys: [
        {
          id: 1,
          key_prefix: "sk-ah-test",
          name: "Test Key",
          project_id: "default",
          rate_limit_rpm: 60,
          rate_limit_tpm: 100000,
          is_active: true,
          last_used_at: null,
          created_at: "2026-01-01T00:00:00Z",
          expires_at: null,
        },
      ],
      total: 1,
    });

    render(<APIKeysPage />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText("Test Key")).toBeInTheDocument();
      expect(screen.getByText("sk-ah-test...")).toBeInTheDocument();
    });
  });

  it("shows create key button", async () => {
    mockFetchAPIKeys.mockResolvedValue({ keys: [], total: 0 });
    render(<APIKeysPage />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /create key/i }),
      ).toBeInTheDocument();
    });
  });

  it("opens create form when clicking create button", async () => {
    mockFetchAPIKeys.mockResolvedValue({ keys: [], total: 0 });
    const user = userEvent.setup();
    render(<APIKeysPage />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /create key/i }),
      ).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: /create key/i }));

    expect(screen.getByText(/create new api key/i)).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/my api key/i)).toBeInTheDocument();
  });

  it("shows newly created key with copy button", async () => {
    mockFetchAPIKeys.mockResolvedValue({ keys: [], total: 0 });
    mockCreateAPIKey.mockResolvedValue({
      id: 1,
      key: "sk-ah-full-key-here",
      key_prefix: "sk-ah-full",
      name: "New Key",
      project_id: "default",
      rate_limit_rpm: 60,
      rate_limit_tpm: 100000,
      is_active: true,
      last_used_at: null,
      created_at: "2026-01-01T00:00:00Z",
      expires_at: null,
    });

    const user = userEvent.setup();
    render(<APIKeysPage />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /create key/i }),
      ).toBeInTheDocument();
    });

    // Open form
    await user.click(screen.getByRole("button", { name: /create key/i }));

    // Fill name and submit
    await user.type(screen.getByPlaceholderText(/my api key/i), "New Key");
    await user.click(screen.getByRole("button", { name: /create api key/i }));

    await waitFor(() => {
      expect(screen.getByText("sk-ah-full-key-here")).toBeInTheDocument();
      expect(screen.getByText(/save this key now/i)).toBeInTheDocument();
    });
  });

  it("shows revoked badge for inactive keys", async () => {
    mockFetchAPIKeys.mockResolvedValue({
      keys: [
        {
          id: 1,
          key_prefix: "sk-ah-revoked",
          name: "Revoked Key",
          project_id: "default",
          rate_limit_rpm: 60,
          rate_limit_tpm: 100000,
          is_active: false,
          last_used_at: null,
          created_at: "2026-01-01T00:00:00Z",
          expires_at: null,
        },
      ],
      total: 1,
    });

    render(<APIKeysPage />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText("Revoked")).toBeInTheDocument();
    });
  });

  it("shows usage instructions section", async () => {
    mockFetchAPIKeys.mockResolvedValue({ keys: [], total: 0 });
    render(<APIKeysPage />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText(/usage with openai sdk/i)).toBeInTheDocument();
    });
  });

  it("displays rate limits for keys", async () => {
    mockFetchAPIKeys.mockResolvedValue({
      keys: [
        {
          id: 1,
          key_prefix: "sk-ah-test",
          name: "Test Key",
          project_id: "default",
          rate_limit_rpm: 120,
          rate_limit_tpm: 200000,
          is_active: true,
          last_used_at: null,
          created_at: "2026-01-01T00:00:00Z",
          expires_at: null,
        },
      ],
      total: 1,
    });

    render(<APIKeysPage />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText(/120 rpm/)).toBeInTheDocument();
      expect(screen.getByText(/200K tpm/)).toBeInTheDocument();
    });
  });
});
