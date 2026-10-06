import type { Project } from "@powereditor/composition";
import { ApiError, readBody, request } from "./client";
import type {
  ExportFile,
  FeatureModels,
  JobInfo,
  ModelInfo,
  ProjectListItem,
  ProjectOptions,
  Provider,
  ProviderDraft,
  ProviderKindInfo,
  ProviderTestResult,
  SecretStatus,
  SettingsResponse,
  SetupStatus,
  SubtitleFormat,
  UserSettings,
} from "./types";

const providerPath = (id: string) => `/api/providers/${encodeURIComponent(id)}`;
export const projectPath = (id: string) => `/api/projects/${encodeURIComponent(id)}`;
const jobPath = (id: string) => `/api/jobs/${encodeURIComponent(id)}`;

/** The analyzed project with the ETag a later save must send back. */
async function readProject(id: string): Promise<{ project: Project; etag: string }> {
  let response: Response;
  try {
    response = await fetch(projectPath(id));
  } catch {
    throw new ApiError(0, "network", "The local server is not reachable.");
  }
  const project = await readBody<Project>(response);
  return { project, etag: response.headers.get("ETag") ?? "" };
}

/** Save an edited project over the revision `etag` names; resolves to the new ETag. A stale
 * ETag fails with a 409 `revision_conflict`. `keepalive` lets the save outlive a closing page. */
async function saveProject(
  id: string,
  project: Project,
  etag: string,
  options: { keepalive?: boolean } = {},
): Promise<string> {
  let response: Response;
  try {
    response = await fetch(projectPath(id), {
      method: "PUT",
      headers: { "Content-Type": "application/json", "If-Match": etag },
      body: JSON.stringify(project),
      keepalive: options.keepalive ?? false,
    });
  } catch {
    throw new ApiError(0, "network", "The local server is not reachable.");
  }
  await readBody<Project>(response);
  return response.headers.get("ETag") ?? "";
}

export const api = {
  setup: () => request<SetupStatus>("GET", "/api/setup"),
  downloadWhisperModel: () => request<JobInfo>("POST", "/api/setup/whisper-model"),

  settings: () => request<SettingsResponse>("GET", "/api/settings"),
  updateSettings: (changes: Partial<UserSettings>) =>
    request<SettingsResponse>("PATCH", "/api/settings", changes),
  storeOpenAiKey: (value: string) =>
    request<SecretStatus>("PUT", "/api/secrets/openai_api_key", { value }),
  clearOpenAiKey: () => request<SecretStatus>("DELETE", "/api/secrets/openai_api_key"),

  providerKinds: () => request<ProviderKindInfo[]>("GET", "/api/providers/kinds"),
  providers: () => request<Provider[]>("GET", "/api/providers"),
  createProvider: (draft: ProviderDraft) => request<Provider>("POST", "/api/providers", draft),
  updateProvider: (id: string, changes: Partial<ProviderDraft>) =>
    request<Provider>("PATCH", providerPath(id), changes),
  deleteProvider: (id: string) => request<undefined>("DELETE", providerPath(id)),
  storeProviderKey: (id: string, value: string) =>
    request<{ set: boolean }>("PUT", `${providerPath(id)}/api-key`, { value }),
  testProvider: (id: string) => request<ProviderTestResult>("POST", `${providerPath(id)}/test`),
  providerModels: (id: string) => request<ModelInfo[]>("GET", `${providerPath(id)}/models`),

  featureModels: () => request<{ features: FeatureModels }>("GET", "/api/features/models"),
  saveFeatureModels: (features: FeatureModels) =>
    request<{ features: FeatureModels }>("PUT", "/api/features/models", { features }),

  projects: () => request<ProjectListItem[]>("GET", "/api/projects"),
  createProject: (paths: string[], options: ProjectOptions) =>
    request<{ id: string }>("POST", "/api/projects", { paths, ...options }),
  project: readProject,
  saveProject,
  deleteProject: (id: string) => request<undefined>("DELETE", projectPath(id)),
  analyze: (id: string) => request<JobInfo>("POST", `${projectPath(id)}/analyze`),
  render: (id: string, exportName: string) =>
    request<JobInfo>("POST", `${projectPath(id)}/render`, { exportName }),
  exportSubtitles: (id: string, format: SubtitleFormat, name: string) =>
    request<JobInfo>("POST", `${projectPath(id)}/export/subtitles`, { format, name }),
  exports: (id: string) => request<ExportFile[]>("GET", `${projectPath(id)}/exports`),
  revealExport: (id: string, file: string) =>
    request<undefined>("POST", `${projectPath(id)}/exports/${encodeURIComponent(file)}/reveal`),

  job: (id: string) => request<JobInfo>("GET", jobPath(id)),
  cancelJob: (id: string) => request<JobInfo>("POST", `${jobPath(id)}/cancel`),
};
