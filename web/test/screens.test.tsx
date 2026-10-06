import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../src/api/client";
import { api } from "../src/api/endpoints";
import { watchJob } from "../src/api/jobs";
import type { FeatureModels, Provider, SettingsResponse, SetupStatus } from "../src/api/types";
import { translate, type MessageKey } from "../src/i18n";
import { FeaturesScreen } from "../src/settings/FeaturesScreen";
import { ProvidersScreen } from "../src/settings/ProvidersScreen";
import { SettingsScreen } from "../src/settings/SettingsScreen";
import { SetupScreen } from "../src/settings/SetupScreen";
import { useAppStore } from "../src/store/app";

vi.mock("../src/api/endpoints", () => ({
  api: Object.fromEntries(
    [
      "setup",
      "downloadWhisperModel",
      "settings",
      "updateSettings",
      "providerKinds",
      "providers",
      "createProvider",
      "storeProviderKey",
      "featureModels",
      "saveFeatureModels",
    ].map((name) => [name, vi.fn()]),
  ),
}));
vi.mock("../src/api/jobs", () => ({ watchJob: vi.fn(() => () => undefined) }));

const t = (key: MessageKey, vars?: Record<string, string | number>) => translate("en", key, vars);

beforeEach(() => {
  vi.clearAllMocks();
  useAppStore.setState({ language: "en" });
});

const SETUP: SetupStatus = {
  doctor: {
    system: "Windows",
    machine: "ARM64",
    ok: false,
    checks: [
      { name: "ffmpeg", required: true, found: false, version: null, detail: "not found" },
      { name: "node", required: true, found: true, version: "v24.1.0", detail: null },
    ],
  },
  transcriber: "local",
  whisperModel: "small",
  whisperModelDownloaded: false,
  openaiKeySet: false,
  transcriberReady: false,
  ready: false,
  whisperDownloadJobId: null,
};

describe("SetupScreen", () => {
  it("shows missing tools with a fix hint and downloads the model with progress", async () => {
    vi.mocked(api.setup).mockResolvedValue(SETUP);
    vi.mocked(api.downloadWhisperModel).mockResolvedValue({
      id: "job-1",
      status: "queued",
      stage: null,
      fraction: 0,
    });
    vi.mocked(watchJob).mockImplementation((_id, onEvent) => {
      onEvent({
        jobId: "job-1",
        status: "running",
        stage: "download",
        fraction: 0.4,
        message: "",
        error: null,
      });
      return () => undefined;
    });
    render(<SetupScreen />);

    expect(await screen.findByText(t("setup.hint.ffmpeg"))).toBeTruthy();
    expect(screen.getByText(t("setup.notReady"))).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: t("setup.download") }));

    expect(watchJob).toHaveBeenCalledWith("job-1", expect.any(Function));
    expect(await screen.findByText(t("setup.downloading", { percent: 40 }))).toBeTruthy();
  });
});

const SETTINGS: SettingsResponse = {
  settings: {
    transcriber: "local",
    whisperModel: null,
    whisperDevice: "auto",
    language: "es",
    modelMinConfidence: 0.8,
    takeWeights: { completeness: 4, fillers: 0.5 },
    silencePaddingMs: 120,
    audioCrossfadeMs: 15,
    targetLufs: -14,
    punchInScale: 1.1,
    ffmpegPath: null,
    ffprobePath: null,
    nodePath: null,
    uiLanguage: "en",
  },
  resolvedWhisperModel: "small",
  secrets: {
    openaiApiKey: { set: false, source: null },
    typesafeApiKey: { set: false, source: null },
  },
};

describe("SettingsScreen", () => {
  it("sends only the changed fields with numbers as numbers", async () => {
    vi.mocked(api.settings).mockResolvedValue(SETTINGS);
    vi.mocked(api.updateSettings).mockResolvedValue(SETTINGS);
    render(<SettingsScreen />);

    const lufs = await screen.findByLabelText(t("settings.targetLufs"));
    await userEvent.clear(lufs);
    await userEvent.type(lufs, "-16");
    await userEvent.type(screen.getByLabelText(t("settings.nodePath")), "C:/node-x64/node.exe");
    await userEvent.clear(screen.getByLabelText(t("weight.fillers")));
    await userEvent.type(screen.getByLabelText(t("weight.fillers")), "1");
    await userEvent.click(screen.getByRole("button", { name: t("common.save") }));

    expect(api.updateSettings).toHaveBeenCalledWith({
      targetLufs: -16,
      nodePath: "C:/node-x64/node.exe",
      takeWeights: { fillers: 1 },
    });
    expect(await screen.findByText(t("common.saved"))).toBeTruthy();
  });

  it("shows the backend's validation message on the field", async () => {
    vi.mocked(api.settings).mockResolvedValue(SETTINGS);
    vi.mocked(api.updateSettings).mockRejectedValue(
      new ApiError(422, "validation", "bad", { punchInScale: "Input should be greater than 0" }),
    );
    render(<SettingsScreen />);

    const scale = await screen.findByLabelText(t("settings.punchInScale"));
    await userEvent.clear(scale);
    await userEvent.type(scale, "0");
    await userEvent.click(screen.getByRole("button", { name: t("common.save") }));

    expect(await screen.findByText("Input should be greater than 0")).toBeTruthy();
    expect(screen.getByLabelText(t("settings.punchInScale")).getAttribute("aria-invalid")).toBe(
      "true",
    );
  });
});

function provider(overrides: Partial<Provider> = {}): Provider {
  return {
    id: "openai-api",
    kind: "openai",
    transport: "api",
    label: "OpenAI",
    enabledModels: ["gpt-a"],
    cliPath: null,
    baseUrl: null,
    customBaseUrlConfirmed: false,
    apiKeySet: true,
    ...overrides,
  };
}

describe("ProvidersScreen", () => {
  beforeEach(() => {
    vi.mocked(api.providerKinds).mockResolvedValue([
      { kind: "openai", label: "OpenAI", transports: ["api", "local_cli"] },
      { kind: "anthropic", label: "Anthropic Claude", transports: ["api", "local_cli"] },
    ]);
  });

  it("creates an API provider and stores its key separately", async () => {
    vi.mocked(api.providers).mockResolvedValue([]);
    vi.mocked(api.createProvider).mockResolvedValue(provider({ id: "openai-api" }));
    vi.mocked(api.storeProviderKey).mockResolvedValue({ set: true });
    render(<ProvidersScreen />);

    await userEvent.click(await screen.findByRole("button", { name: t("providers.add") }));
    await userEvent.type(screen.getByLabelText(t("providers.apiKey")), "sk-test");
    await userEvent.click(screen.getByRole("button", { name: t("providers.create") }));

    await waitFor(() => expect(api.storeProviderKey).toHaveBeenCalledWith("openai-api", "sk-test"));
    expect(api.createProvider).toHaveBeenCalledWith({
      kind: "openai",
      transport: "api",
      label: "OpenAI",
      enabledModels: [],
      cliPath: null,
      baseUrl: null,
      customBaseUrlConfirmed: false,
    });
  });

  it("blocks a custom base URL until it is confirmed", async () => {
    vi.mocked(api.providers).mockResolvedValue([]);
    render(<ProvidersScreen />);

    await userEvent.click(await screen.findByRole("button", { name: t("providers.add") }));
    await userEvent.type(screen.getByLabelText(t("providers.baseUrl")), "https://proxy.example/v1");
    await userEvent.click(screen.getByRole("button", { name: t("providers.create") }));

    expect(screen.getByText(t("providers.error.confirm"))).toBeTruthy();
    expect(api.createProvider).not.toHaveBeenCalled();
  });

  it("shows the subscription terms for a local Claude client", async () => {
    vi.mocked(api.providers).mockResolvedValue([
      provider({ id: "claude", kind: "anthropic", transport: "local_cli", label: "Claude Code" }),
    ]);
    render(<ProvidersScreen />);

    const card = await screen.findByRole("article", { name: "Claude Code" });
    expect(within(card).getByText(t("terms.claude"))).toBeTruthy();
    expect(within(card).queryByLabelText(t("providers.apiKey"))).toBeNull();
  });
});

describe("FeaturesScreen", () => {
  it("assigns an enabled model to a feature and saves every feature", async () => {
    const none = Object.fromEntries(
      ["off_take_detection", "idea_completeness", "same_take_grey_zone", "fluency_score"]
        .concat(["best_take_choice", "topic_change", "cta_detection"])
        .map((id) => [id, null]),
    ) as FeatureModels;
    vi.mocked(api.providers).mockResolvedValue([provider()]);
    vi.mocked(api.featureModels).mockResolvedValue({ features: none });
    vi.mocked(api.saveFeatureModels).mockImplementation((features) =>
      Promise.resolve({ features }),
    );
    render(<FeaturesScreen />);

    const select = await screen.findByLabelText(t("feature.best_take_choice"));
    expect((select as HTMLSelectElement).value).toBe("");
    await userEvent.selectOptions(select, "openai-api/gpt-a");
    await userEvent.click(screen.getByRole("button", { name: t("common.save") }));

    expect(api.saveFeatureModels).toHaveBeenCalledWith({
      ...none,
      best_take_choice: { providerId: "openai-api", model: "gpt-a" },
    });
    expect(await screen.findByText(t("common.saved"))).toBeTruthy();
  });
});
