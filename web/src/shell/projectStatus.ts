import type { ProjectListItem } from "../api/types";

export type ProjectStatus = "created" | "analyzing" | "rendering" | "ready" | "error";

/** What a project card shows: a running job first, then the last failure, then its files. */
export function projectStatus(project: ProjectListItem): ProjectStatus {
  if (project.activeJobId) return project.activeJobKind === "analyze" ? "analyzing" : "rendering";
  if (project.lastError) return "error";
  return project.status === "analyzed" ? "ready" : "created";
}
