import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../src/api/endpoints";
import { watchJob } from "../src/api/jobs";
import type { JobEvent, JobInfo, RuntimeStatus, SetupStatus } from "../src/api/types";
import { translate, type MessageKey } from "../src/i18n";
import { OnboardingScreen } from "../src/settings/OnboardingScreen";
import { useAppStore } from "../src/store/app";

vi.mock("../src/api/endpoints", () => ({
  api: Object.fromEntries(
    ["setup", "installRuntime", "downloadWhisperModel", "storeOpenAiKey", "updateSettings"].map(
      (name) => [name, vi.fn()],
    ),
  ),
}));
vi.mock("../src/api/jobs", () => ({ watchJob: vi.fn() }));

const t = (key: MessageKey, vars?: Record<string, string | number>) => translate("en", key, vars);

const runtime = (name: string, installed: boolean): RuntimeStatus => ({
  name,
  version: "1",
  supported: true,
  installed,
  path: null,
  downloadBytes: 10 * 2 ** 20,
});

function status(installed: boolean): SetupStatus {
  return {
    doctor: { system: "Windows", machine: "AMD64", ok: installed, checks: [] },
    transcriber: "local",
    whisperModel: "small",
    whisperModelDownloaded: false,
    openaiKeySet: false,
    transcriberReady: false,
    ready: false,
    whisperDownloadJobId: null,
    runtimes: ["ffmpeg", "node", "browser"].map((name) => runtime(name, installed)),
  };
}

const job = (id: string): JobInfo => ({
  id,
  kind: "runtime",
  status: "queued",
  stage: null,
  fraction: 0,
  message: "",
  error: null,
  result: null,
});

const ended = (jobId: string, outcome: Partial<JobEvent> = {}): JobEvent => ({
  jobId,
  status: "succeeded",
  stage: "download",
  fraction: 1,
  message: "",
  error: null,
  result: null,
  ...outcome,
});

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  useAppStore.setState({ language: "en", path: "/welcome" });
  vi.mocked(api.installRuntime).mockImplementation(async (name) => job(`job-${name}`));
});

describe("OnboardingScreen", () => {
  it("downloads every missing runtime in order, then moves on to transcription", async () => {
    vi.mocked(api.setup).mockResolvedValueOnce(status(false)).mockResolvedValue(status(true));
    vi.mocked(watchJob).mockImplementation((jobId, onEvent) => {
      onEvent(ended(jobId));
      return () => undefined;
    });
    render(<OnboardingScreen />);

    await userEvent.click(
      await screen.findByRole("button", { name: t("onboarding.runtimes.installAll") }),
    );

    await waitFor(() =>
      expect(vi.mocked(api.installRuntime).mock.calls.map(([name]) => name)).toEqual([
        "ffmpeg",
        "node",
        "browser",
      ]),
    );
    expect(await screen.findByText(t("onboarding.runtimes.done"))).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: t("onboarding.next") }));
    expect(screen.getByRole("heading", { name: t("onboarding.transcription.title") })).toBeTruthy();
  });

  it("stops at the first failed download and shows why", async () => {
    vi.mocked(api.setup).mockResolvedValue(status(false));
    vi.mocked(watchJob).mockImplementation((jobId, onEvent) => {
      onEvent(
        ended(jobId, {
          status: "failed",
          error: { code: "runtime_checksum_mismatch", message: "bad sum" },
        }),
      );
      return () => undefined;
    });
    render(<OnboardingScreen />);

    await userEvent.click(
      await screen.findByRole("button", { name: t("onboarding.runtimes.installAll") }),
    );

    expect(await screen.findByText(t("error.runtime_checksum_mismatch"))).toBeTruthy();
    expect(api.installRuntime).toHaveBeenCalledTimes(1);
  });

  it("skipping the whole setup is remembered and leaves for the projects", async () => {
    vi.mocked(api.setup).mockResolvedValue(status(false));
    render(<OnboardingScreen />);

    await userEvent.click(await screen.findByRole("button", { name: t("onboarding.skipAll") }));

    expect(localStorage.getItem("powereditor.onboardingSkipped")).toBe("1");
    expect(useAppStore.getState().path).toBe("/");
  });

  it("an OpenAI key switches the transcriber to OpenAI", async () => {
    vi.mocked(api.setup).mockResolvedValue(status(true));
    vi.mocked(api.storeOpenAiKey).mockResolvedValue({ set: true, source: "keyring" });
    render(<OnboardingScreen />);

    await userEvent.click(await screen.findByRole("button", { name: t("onboarding.next") }));
    await userEvent.type(screen.getByLabelText(t("settings.openaiKey")), "sk-test");
    await userEvent.click(screen.getByRole("button", { name: t("secret.save") }));

    await waitFor(() => expect(api.updateSettings).toHaveBeenCalledWith({ transcriber: "openai" }));
    expect(api.storeOpenAiKey).toHaveBeenCalledWith("sk-test");
  });
});
