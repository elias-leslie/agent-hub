import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ActivityTimeline } from "@/app/persona/components/ActivityTimeline";

vi.mock("@/lib/api-config", () => ({
  fetchApi: vi.fn(),
}));

import { fetchApi } from "@/lib/api-config";

function jsonResponse(data: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: vi.fn().mockResolvedValue(data),
  } as unknown as Response;
}

const baseSession = {
  id: "session-1",
  summary_oneliner: null,
  status: "completed",
  message_count: 1,
  created_at: "2026-03-06T14:00:00Z",
  updated_at: "2026-03-06T14:00:00Z",
  events_preview: [],
};

describe("ActivityTimeline", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("treats only heartbeat sessions as routine heartbeat checks", async () => {
    vi.mocked(fetchApi).mockResolvedValueOnce(
      jsonResponse({
        sessions: [{ ...baseSession, session_type: "heartbeat" }],
        total: 1,
        page: 1,
        page_size: 50,
      }),
    );

    render(<ActivityTimeline />);

    await waitFor(() => {
      expect(screen.getByText("Single activity feed")).toBeInTheDocument();
    });

    expect(screen.getByText(/1 routine check passed/)).toBeInTheDocument();
    expect(screen.queryByText("All quiet")).not.toBeInTheDocument();
  });

  it("renders generic completion sessions as autonomous runs instead of heartbeats", async () => {
    vi.mocked(fetchApi).mockResolvedValueOnce(
      jsonResponse({
        sessions: [{ ...baseSession, session_type: "completion" }],
        total: 1,
        page: 1,
        page_size: 50,
      }),
    );

    render(<ActivityTimeline />);

    await waitFor(() => {
      expect(screen.getByText("Autonomous run")).toBeInTheDocument();
    });

    expect(screen.queryByText(/routine check passed/)).not.toBeInTheDocument();
  });

  it("shows an explicit error state when activity fails to load", async () => {
    vi.mocked(fetchApi).mockRejectedValueOnce(new Error("network down"));

    render(<ActivityTimeline />);

    await waitFor(() => {
      expect(screen.getByText("Failed to load activity")).toBeInTheDocument();
    });

    expect(screen.getByText("network down")).toBeInTheDocument();
  });

  it("does not render highlight/all toggle controls anymore", async () => {
    vi.mocked(fetchApi).mockResolvedValueOnce(
      jsonResponse({
        sessions: [{ ...baseSession, session_type: "completion" }],
        total: 1,
        page: 1,
        page_size: 50,
      }),
    );

    render(<ActivityTimeline />);

    await waitFor(() => {
      expect(screen.getByText("Single activity feed")).toBeInTheDocument();
    });

    expect(screen.queryByText("Highlights")).not.toBeInTheDocument();
    expect(screen.queryByText("All")).not.toBeInTheDocument();
  });
});
