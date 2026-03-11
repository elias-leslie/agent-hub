import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import PersonaAnalyticsPage from "@/app/persona/analytics/page";

vi.mock("@/app/agents/[slug]/analytics/components/AgentAnalyticsDashboard", () => ({
  AgentAnalyticsDashboard: ({
    slug,
    backHref,
  }: {
    slug: string;
    backHref?: string;
  }) => (
    <div>
      dashboard:{slug}:{backHref}
    </div>
  ),
}));

describe("PersonaAnalyticsPage", () => {
  it("renders the shared dashboard for persona with persona back navigation", () => {
    render(<PersonaAnalyticsPage />);

    expect(screen.getByText("dashboard:persona:/persona")).toBeInTheDocument();
  });
});
