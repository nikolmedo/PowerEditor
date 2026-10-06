export type Step = "load" | "review" | "export";
export const STEPS: readonly Step[] = ["load", "review", "export"];

export type Route =
  | { screen: "home" }
  | { screen: "setup" | "settings" | "providers" | "features" }
  | { screen: "load"; projectId: string | null }
  | { screen: "review" | "export"; projectId: string };

const STATIC: Record<string, Route> = {
  "/setup": { screen: "setup" },
  "/settings": { screen: "settings" },
  "/settings/providers": { screen: "providers" },
  "/settings/features": { screen: "features" },
  "/load": { screen: "load", projectId: null },
};
const PROJECT_STEP = /^\/projects\/([^/]+)\/(load|review|export)\/?$/;

/** The screen for a URL path; unknown paths show the projects home. */
export function parseRoute(path: string): Route {
  const fixed = STATIC[path];
  if (fixed) return fixed;
  const match = PROJECT_STEP.exec(path);
  if (!match) return { screen: "home" };
  const projectId = decodeURIComponent(match[1] as string);
  return { screen: match[2] as Step, projectId };
}

/** Path of a project's step; without a project only "load" (a new project) exists. */
export function stepPath(step: Step, projectId: string | null): string | null {
  if (projectId) return `/projects/${encodeURIComponent(projectId)}/${step}`;
  return step === "load" ? "/load" : null;
}
