import { useState, useCallback } from "react";
import { useSearchParams } from "next/navigation";

export interface ProjectConfig {
  id: string;
  name: string;
  rootPath: string;
}

/**
 * All projects registered in Agent Hub.
 * Mirrors VALID_PROJECT_IDS from backend/app/constants/projects.py
 * (excluding utility scopes like st-cli, consult, etc.)
 */
export const PROJECTS: ProjectConfig[] = [
  { id: "agent-hub", name: "Agent Hub", rootPath: "/home/kasadis/agent-hub" },
  { id: "summitflow", name: "SummitFlow", rootPath: "/home/kasadis/summitflow" },
  { id: "portfolio-ai", name: "Portfolio AI", rootPath: "/home/kasadis/portfolio-ai" },
  { id: "terminal", name: "Terminal", rootPath: "/home/kasadis/terminal" },
  { id: "monkey-fight", name: "Monkey Fight", rootPath: "/home/kasadis/monkey-fight" },
];

interface UseProjectContextReturn {
  projects: ProjectConfig[];
  selectedProject: ProjectConfig;
  setSelectedProject: (project: ProjectConfig) => void;
}

export function useProjectContext(): UseProjectContextReturn {
  const searchParams = useSearchParams();
  const projectFromUrl = searchParams.get("project");

  const [selectedProject, setSelectedProject] = useState<ProjectConfig>(() => {
    if (projectFromUrl) {
      const found = PROJECTS.find((p) => p.id === projectFromUrl);
      if (found) return found;
    }
    return PROJECTS[0]; // Default: agent-hub
  });

  const handleSetProject = useCallback((project: ProjectConfig) => {
    setSelectedProject(project);
    // Update URL with project context (using replaceState to avoid remount)
    if (typeof window !== "undefined") {
      const url = new URL(window.location.href);
      url.searchParams.set("project", project.id);
      window.history.replaceState(null, "", url.toString());
    }
  }, []);

  return {
    projects: PROJECTS,
    selectedProject,
    setSelectedProject: handleSetProject,
  };
}
