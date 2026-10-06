import { request } from "./client";
import type {
  FeatureModels,
  JobInfo,
  ModelInfo,
  ProjectListItem,
  Provider,
  ProviderDraft,
  ProviderKindInfo,
  ProviderTestResult,
  SecretStatus,
  SettingsResponse,
  SetupStatus,
  UserSettings,
} from "./types";

const providerPath = (id: string) => `/api/providers/${encodeURIComponent(id)}`;

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
};
