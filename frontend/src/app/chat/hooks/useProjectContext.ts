export interface ProjectConfig {
  id: string;
  name: string;
  rootPath: string;
}

/**
 * All projects registered in Agent Hub.
 * TODO: Fetch dynamically from GET /api/projects instead of hardcoding.
 * Backend VALID_PROJECT_IDS now derives from project_permissions table.
 */
export const PROJECTS: ProjectConfig[] = [
  { id: "persona-sandbox", name: "Persona Sandbox", rootPath: "/home/kasadis/persona-sandbox" },
  { id: "agent-hub", name: "Agent Hub", rootPath: "/home/kasadis/agent-hub" },
  { id: "summitflow", name: "SummitFlow", rootPath: "/home/kasadis/summitflow" },
  { id: "portfolio-ai", name: "Portfolio AI", rootPath: "/home/kasadis/portfolio-ai" },
  { id: "terminal", name: "Terminal", rootPath: "/home/kasadis/terminal" },
  { id: "monkey-fight", name: "Monkey Fight", rootPath: "/home/kasadis/monkey-fight" },
];
