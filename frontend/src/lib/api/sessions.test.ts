import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

describe("fetchAllSessionEvents", () => {
  const originalEnv = { ...process.env };
  const originalWindow = globalThis.window;

  beforeEach(() => {
    vi.resetModules();
    process.env = { ...originalEnv };
    vi.stubGlobal("window", undefined);
  });

  afterEach(() => {
    process.env = originalEnv;
    if (originalWindow === undefined) {
      Reflect.deleteProperty(globalThis, "window");
    } else {
      vi.stubGlobal("window", originalWindow);
    }
    vi.restoreAllMocks();
  });

  it("caps event page size at backend max", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          session_id: "session-123",
          events: [],
          total: 0,
          max_turn: 0,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const { fetchAllSessionEvents } = await import("./sessions");

    await fetchAllSessionEvents("session-123", { page_size: 1000 });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8003/api/sessions/session-123/events?page=1&page_size=500",
      expect.any(Object),
    );
  });
});
