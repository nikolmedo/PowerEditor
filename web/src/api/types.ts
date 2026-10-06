/** Shapes of the local API (`backend/powereditor/api/`), camelCase as the backend sends them. */

export type Transport = "api" | "local_cli";
export type Transcriber = "local" | "openai";
export type WhisperDevice = "auto" | "cuda" | "cpu";

export const FEATURE_IDS = [
  "off_take_detection",
  "idea_completeness",
  "same_take_grey_zone",
  "fluency_score",
  "best_take_choice",
  "topic_change",
  "cta_detection",
] as const;
export type FeatureId = (typeof FEATURE_IDS)[number];

export interface ModelRef {
  providerId: string;
  model: string;
}

export interface UserSettings {
  transcriber: Transcriber;
  whisperModel: string | null;
  whisperDevice: WhisperDevice;
  language: string | null;
  modelMinConfidence: number;
  takeWeights: Record<string, number>;
  silencePaddingMs: number;
  audioCrossfadeMs: number;
  targetLufs: number;
  punchInScale: number;
  autoCta: boolean;
  /** Browser tabs per render; 0 picks them from the cores and free memory. */
  renderMaxConcurrency: number;
  ffmpegPath: string | null;
  ffprobePath: string | null;
  nodePath: string | null;
  uiLanguage: string;
}

export interface SecretStatus {
  set: boolean;
  source: "env" | "keyring" | null;
}

export interface SettingsResponse {
  settings: UserSettings;
  resolvedWhisperModel: string;
  secrets: { openaiApiKey: SecretStatus; typesafeApiKey: SecretStatus };
}

export interface DependencyCheck {
  name: string;
  required: boolean;
  found: boolean;
  version: string | null;
  detail: string | null;
}

/** A runtime the app downloads into its data dir (`GET /api/setup`). */
export interface RuntimeStatus {
  name: string;
  version: string | null;
  supported: boolean;
  installed: boolean;
  /** The installed executable. */
  path: string | null;
  downloadBytes: number | null;
}

export interface SetupStatus {
  doctor: { system: string; machine: string; checks: DependencyCheck[]; ok: boolean };
  transcriber: Transcriber;
  whisperModel: string;
  whisperModelDownloaded: boolean;
  openaiKeySet: boolean;
  transcriberReady: boolean;
  ready: boolean;
  whisperDownloadJobId: string | null;
  runtimes: RuntimeStatus[];
}

export interface ProviderKindInfo {
  kind: string;
  label: string;
  transports: Transport[];
}

export interface Provider {
  id: string;
  kind: string;
  transport: Transport;
  label: string;
  enabledModels: string[];
  cliPath: string | null;
  baseUrl: string | null;
  customBaseUrlConfirmed: boolean;
  apiKeySet: boolean;
}

export type ProviderDraft = Omit<Provider, "id" | "apiKeySet">;

export interface ProviderTestResult {
  ok: boolean;
  detail: string;
  code: string | null;
  version: string | null;
  authenticated: boolean | null;
}

export interface ModelInfo {
  id: string;
  label: string | null;
  note: string | null;
}

export type FeatureModels = Record<FeatureId, ModelRef | null>;

export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";
export type JobKind = "analyze" | "render" | "export_subtitles" | "whisper_model" | "runtime";

export interface JobError {
  code: string;
  message: string;
}

export interface JobEvent {
  jobId: string;
  status: JobStatus;
  stage: string | null;
  fraction: number;
  message: string;
  error: JobError | null;
  result: Record<string, unknown> | null;
}

export interface JobInfo {
  id: string;
  kind: JobKind;
  status: JobStatus;
  stage: string | null;
  fraction: number;
  message: string;
  error: JobError | null;
  result: Record<string, unknown> | null;
}

export type ProjectPreset = "reel_9x16" | "landscape_16x9";

/** A music file stored in a project's media folder (`POST /api/projects/{id}/music`). */
export interface MusicFile {
  fileName: string;
  durationSeconds: number;
  url: string;
}

/** An overlay image stored in a project's media folder (`POST /api/projects/{id}/overlay-assets`). */
export interface OverlayAsset {
  fileName: string;
  url: string;
}

export interface ProjectOptions {
  name?: string;
  preset?: ProjectPreset;
  language?: string;
  script?: string;
}

export interface ProjectListItem {
  id: string;
  name: string;
  createdAt: string;
  status: "created" | "ingested" | "analyzed";
  durationSeconds: number | null;
  thumbnailUrl: string | null;
  activeJobId: string | null;
  activeJobKind: JobKind | null;
  lastError: JobError | null;
}

export interface ExportFile {
  name: string;
  sizeBytes: number;
  modifiedAt: string;
  url: string;
}

export type SubtitleFormat = "srt" | "ass";

/** Export quality presets of `POST /api/projects/{id}/render`. */
export type RenderQuality = "draft" | "standard" | "high";
