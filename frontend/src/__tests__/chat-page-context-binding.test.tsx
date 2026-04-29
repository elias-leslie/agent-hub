import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ChatPage from "@/app/chat/page";

const mocks = vi.hoisted(() => ({
  routerPush: vi.fn(),
  fetchApi: vi.fn(),
  fetchProjectPermissions: vi.fn(),
  fetchProjectRoots: vi.fn(),
  searchTasks: vi.fn(),
  chatPanelProps: [] as Array<Record<string, unknown>>,
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: mocks.routerPush,
  }),
  useSearchParams: () => ({
    get: () => null,
  }),
}));

vi.mock("@/components/chat", () => ({
  ChatPanel: (props: Record<string, unknown>) => {
    mocks.chatPanelProps.push(props);
    return (
      <div
        data-testid="chat-panel"
        data-agent={String(props.agentSlug ?? "")}
        data-project={String(props.projectId ?? "")}
        data-session={String(props.sessionId ?? "")}
        data-working-dir={String(props.workingDir ?? "")}
        data-external-id={String(props.externalId ?? "")}
      />
    );
  },
}));

vi.mock("@/lib/api-config", () => ({
  getApiBaseUrl: () => "",
  fetchApi: (...args: unknown[]) => mocks.fetchApi(...args),
}));

vi.mock("@/lib/api", () => ({
  fetchProjectPermissions: (...args: unknown[]) => mocks.fetchProjectPermissions(...args),
  fetchProjectRoots: (...args: unknown[]) => mocks.fetchProjectRoots(...args),
}));

vi.mock("@/lib/api/tasks", () => ({
  searchTasks: (...args: unknown[]) => mocks.searchTasks(...args),
}));

function latestChatPanelProps() {
  return mocks.chatPanelProps[mocks.chatPanelProps.length - 1];
}

describe("ChatPage context binding", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.chatPanelProps.length = 0;
    localStorage.clear();
    localStorage.setItem("persona_active_session_id", "stale-agent-hub-session");
    mocks.fetchApi.mockResolvedValue({
      ok: true,
      json: async () => ({
        agents: [
          {
            slug: "chat",
            name: "General Assistant",
            primary_model_id: "codex/gpt-5.4",
          },
          {
            slug: "refactor",
            name: "Refactoring Agent",
            primary_model_id: "codex/gpt-5.5",
          },
          {
            slug: "debugger",
            name: "Debugger",
            primary_model_id: "codex/gpt-5.4",
          },
        ],
      }),
    });
    mocks.fetchProjectPermissions.mockResolvedValue([
      {
        project_id: "agent-hub",
        permission_tier: "write",
        auto_exec_enabled: true,
        execution_start_hour: 0,
        execution_end_hour: 24,
        root_path: "/srv/workspaces/projects/agent-hub",
        created_at: "2026-04-29T00:00:00Z",
        updated_at: "2026-04-29T00:00:00Z",
      },
      {
        project_id: "summitflow",
        permission_tier: "write",
        auto_exec_enabled: true,
        execution_start_hour: 0,
        execution_end_hour: 24,
        root_path: "/home/kasadis/summitflow",
        created_at: "2026-04-29T00:00:00Z",
        updated_at: "2026-04-29T00:00:00Z",
      },
    ]);
    mocks.fetchProjectRoots.mockResolvedValue({
      "agent-hub": "/srv/workspaces/projects/agent-hub",
      summitflow: "/srv/workspaces/projects/summitflow",
    });
    mocks.searchTasks.mockResolvedValue({
      tasks: [
        {
          id: "task-6b0493a5",
          project_id: "summitflow",
          title: "Fix noisy st done closeout",
          description: "No checkpoint closeout prints stale subtask branch noise.",
          status: "pending",
          priority: 2,
          task_type: "bug",
        },
      ],
      total: 1,
    });
  });

  it("starts a fresh thread when project, agent, or task context changes", async () => {
    render(<ChatPage />);

    await waitFor(() => {
      expect(screen.getByTestId("chat-panel")).toHaveAttribute("data-session", "stale-agent-hub-session");
    });

    fireEvent.click(await screen.findByRole("button", { name: /Summitflow\s*summitflow/i }));

    await waitFor(() => {
      expect(latestChatPanelProps()).toEqual(
        expect.objectContaining({
          sessionId: undefined,
          projectId: "summitflow",
          workingDir: "/srv/workspaces/projects/summitflow",
        }),
      );
    });

    fireEvent.click(screen.getByTestId("model-selector"));
    fireEvent.click(screen.getByRole("button", { name: /Debugger\s*debugger/i }));

    await waitFor(() => {
      expect(latestChatPanelProps()).toEqual(
        expect.objectContaining({
          agentSlug: "debugger",
          sessionId: undefined,
          projectId: "summitflow",
        }),
      );
    });

    fireEvent.click(await screen.findByRole("button", { name: /task-6b0493a5/i }));

    await waitFor(() => {
      expect(latestChatPanelProps()).toEqual(
        expect.objectContaining({
          agentSlug: "debugger",
          sessionId: undefined,
          projectId: "summitflow",
          workingDir: "/srv/workspaces/projects/summitflow",
          externalId: "task-6b0493a5",
        }),
      );
    });
  });
});
