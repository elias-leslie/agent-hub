import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PersonaBackgroundInbox } from "@/app/persona/components/PersonaBackgroundInbox";

describe("PersonaBackgroundInbox", () => {
  it("explains that lane actions stay grounded in current session primitives", () => {
    render(
      <PersonaBackgroundInbox
        entries={[]}
        activeChildSessions={[]}
        activeSessionId={null}
        stoppingSessionId={null}
        onSelectSession={vi.fn()}
        onStopSession={vi.fn()}
        onRedirectSession={vi.fn()}
        onPromoteSession={vi.fn()}
        onHandoffSession={vi.fn()}
      />,
    );

    expect(
      screen.getByText(/actions reuse current session primitives/i),
    ).toBeInTheDocument();
  });
});
