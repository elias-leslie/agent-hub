import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import PersonaArenaPage from "@/app/persona/arena/page";

const mockArenaDashboard = vi.fn(
  ({ slug, backHref }: { slug: string; backHref?: string }) => (
    <div>
      arena:{slug}:{backHref ?? "none"}
    </div>
  ),
);

vi.mock("@/app/agents/[slug]/arena/components/AgentArenaDashboard", () => ({
  AgentArenaDashboard: (props: { slug: string; backHref?: string }) =>
    mockArenaDashboard(props),
}));

describe("PersonaArenaPage", () => {
  it("routes the persona workspace into the shared Arena dashboard", () => {
    render(<PersonaArenaPage />);

    expect(screen.getByText("arena:persona:/persona")).toBeInTheDocument();
    expect(mockArenaDashboard).toHaveBeenCalledWith(
      expect.objectContaining({
        slug: "persona",
        backHref: "/persona",
      }),
    );
  });
});
