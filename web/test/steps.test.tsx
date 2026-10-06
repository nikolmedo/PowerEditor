import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { forwardRef, useImperativeHandle } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../src/api/client";
import { api } from "../src/api/endpoints";
import { watchJob } from "../src/api/jobs";
import type { JobEvent, JobInfo, ProjectListItem } from "../src/api/types";
import { translate, type MessageKey } from "../src/i18n";
import { ReviewStep } from "../src/review/ReviewStep";
import { ProjectsHome } from "../src/shell/ProjectsHome";
import { ExportStep } from "../src/steps/ExportStep";
import { LoadStep } from "../src/steps/LoadStep";
import { useAppStore } from "../src/store/app";
import { PROJECT } from "./fixtures/reviewProject";

vi.mock("../src/api/endpoints", () => ({
  api: Object.fromEntries(
    [
      "setup",
      "settings",
      "projects",
      "createProject",
      "deleteProject",
      "analyze",
      "project",
      "render",
      "exportSubtitles",
      "exports",
      "revealExport",
      "cancelJob",
    ].map((name) => [name, vi.fn()]),
  ),
}));
vi.mock("../src/api/jobs", () => ({ watchJob: vi.fn(() => () => undefined) }));

const seekTo = vi.fn();
vi.mock("@remotion/player", () => ({
  // jsdom cannot play video: a stand-in exposing the ref methods the step uses.
  Player: forwardRef(function FakePlayer(_props, ref) {
    useImperativeHandle(ref, () => ({
      seekTo,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    }));
    return <div data-testid="player" />;
  }),
}));

const t = (key: MessageKey, vars?: Record<string, string | number>) => translate("en", key, vars);

const item = (overrides: Partial<ProjectListItem> = {}): ProjectListItem => ({
  id: "p1",
  name: "Demo",
  createdAt: "2026-10-06T10:00:00Z",
  status: "analyzed",
  durationSeconds: 65,
  thumbnailUrl: null,
  activeJobId: null,
  activeJobKind: null,
  lastError: null,
  ...overrides,
});

const job = (overrides: Partial<JobInfo> = {}): JobInfo => ({
  id: "job-1",
  kind: "analyze",
  status: "queued",
  stage: null,
  fraction: 0,
  message: "",
  error: null,
  result: null,
  ...overrides,
});

function emitting(event: Partial<JobEvent>) {
  vi.mocked(watchJob).mockImplementation((jobId, onEvent) => {
    onEvent({
      jobId,
      status: "running",
      stage: null,
      fraction: 0,
      message: "",
      error: null,
      result: null,
      ...event,
    });
    return () => undefined;
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  useAppStore.setState({ language: "en", path: "/" });
  vi.mocked(api.setup).mockResolvedValue({
    doctor: { system: "Windows", machine: "AMD64", checks: [], ok: true },
    transcriber: "local",
    whisperModel: "small",
    whisperModelDownloaded: true,
    openaiKeySet: false,
    transcriberReady: true,
    ready: true,
    whisperDownloadJobId: null,
  });
});

describe("ProjectsHome", () => {
  it("shows each project's state and deletes only after confirming", async () => {
    vi.mocked(api.projects)
      .mockResolvedValueOnce([
        item(),
        item({ id: "p2", name: "Busy", activeJobId: "j", activeJobKind: "render" }),
      ])
      .mockResolvedValueOnce([]);
    vi.mocked(api.deleteProject).mockResolvedValue(undefined);
    render(<ProjectsHome />);

    const card = await screen.findByRole("listitem", { name: "Demo" });
    expect(within(card).getByText(t("projects.status.ready"))).toBeTruthy();
    const busy = screen.getByRole("listitem", { name: "Busy" });
    expect(within(busy).getByText(t("projects.status.rendering"))).toBeTruthy();
    expect(within(busy).getByRole("button", { name: t("common.delete") })).toHaveProperty(
      "disabled",
      true,
    );

    await userEvent.click(within(card).getByRole("button", { name: t("common.delete") }));
    expect(api.deleteProject).not.toHaveBeenCalled();
    await userEvent.click(within(card).getByRole("button", { name: t("projects.confirmDelete") }));

    expect(api.deleteProject).toHaveBeenCalledWith("p1");
    expect(await screen.findByText(t("projects.empty"))).toBeTruthy();
  });
});

describe("LoadStep", () => {
  it("creates a project from local paths, starts processing and opens its page", async () => {
    vi.mocked(api.createProject).mockResolvedValue({ id: "p9" });
    vi.mocked(api.analyze).mockResolvedValue(job());
    render(<LoadStep projectId={null} />);

    await userEvent.click(screen.getByRole("tab", { name: t("load.mode.paths") }));
    await userEvent.type(screen.getByLabelText(t("load.paths")), '"C:/rec/a.mp4"{enter}D:/b.mp4');
    await userEvent.click(screen.getByLabelText(t("preset.landscape_16x9")));
    await userEvent.click(screen.getByRole("button", { name: t("load.process") }));

    await waitFor(() => expect(useAppStore.getState().path).toBe("/projects/p9/load"));
    expect(api.createProject).toHaveBeenCalledWith(["C:/rec/a.mp4", "D:/b.mp4"], {
      preset: "landscape_16x9",
    });
    expect(api.analyze).toHaveBeenCalledWith("p9");
  });

  it("follows a running analysis stage by stage and can cancel it", async () => {
    vi.mocked(api.projects).mockResolvedValue([
      item({ status: "ingested", activeJobId: "job-1", activeJobKind: "analyze" }),
    ]);
    vi.mocked(api.cancelJob).mockResolvedValue(job({ status: "cancelled" }));
    emitting({ stage: "vad-s1", fraction: 0.5 });
    render(<LoadStep projectId="p1" />);

    const active = (await screen.findByText(t("stage.vad"))).closest("li") as HTMLElement;
    expect(within(active).getByText("50 %")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: t("job.cancel") }));
    expect(api.cancelJob).toHaveBeenCalledWith("job-1");
  });

  it("explains a failed analysis and links to the screen that fixes it", async () => {
    vi.mocked(api.projects).mockResolvedValue([
      item({
        status: "ingested",
        lastError: { code: "missing_openai_key", message: "Set an OpenAI API key" },
      }),
    ]);
    render(<LoadStep projectId="p1" />);

    expect(await screen.findByText(t("error.missing_openai_key"))).toBeTruthy();
    expect(screen.getByRole("link", { name: t("action.settings") }).getAttribute("href")).toBe(
      "/settings",
    );
  });
});

describe("ReviewStep", () => {
  beforeEach(() => {
    vi.mocked(api.settings).mockRejectedValue(new ApiError(0, "network", "offline"));
  });

  it("shows clip details and seeks the player when a clip is picked", async () => {
    vi.mocked(api.project).mockResolvedValue({ project: PROJECT, etag: '"e1"' });
    render(<ReviewStep projectId="p1" />);

    expect(await screen.findByText(t("review.takes", { count: 2 }))).toBeTruthy();
    await userEvent.click(
      screen.getByRole("button", { name: t("review.clipAt", { time: "0:02.0" }) }),
    );

    const panel = screen.getByRole("complementary", { name: t("review.clip") });
    expect(within(panel).getByText("cam-b.MOV")).toBeTruthy();
    expect(within(panel).getByText("95 %")).toBeTruthy();
    expect(seekTo).toHaveBeenCalledWith(60);
  });

  it("sends an unprocessed project back to the load step", async () => {
    vi.mocked(api.project).mockRejectedValue(
      new ApiError(409, "project_not_analyzed", "not analyzed"),
    );
    render(<ReviewStep projectId="p1" />);

    expect(await screen.findByText(t("review.notAnalyzed"))).toBeTruthy();
    expect(screen.getByRole("link", { name: t("review.toLoad") }).getAttribute("href")).toBe(
      "/projects/p1/load",
    );
  });
});

describe("ExportStep", () => {
  it("renders, shows the result and opens its folder", async () => {
    const file = {
      name: "final.mp4",
      sizeBytes: 3 * 1024 * 1024,
      modifiedAt: "2026-10-06T10:00:00Z",
      url: "/api/projects/p1/media/final.mp4",
    };
    vi.mocked(api.projects).mockResolvedValue([item()]);
    vi.mocked(api.exports).mockResolvedValueOnce([]).mockResolvedValue([file]);
    vi.mocked(api.render).mockResolvedValue(job({ id: "job-2", kind: "render" }));
    vi.mocked(api.revealExport).mockResolvedValue(undefined);
    emitting({ status: "succeeded", fraction: 1, result: { file: "final.mp4", wallSeconds: 42 } });
    render(<ExportStep projectId="p1" />);

    await userEvent.click(await screen.findByRole("button", { name: t("export.render") }));

    const result = await screen.findByRole("status");
    expect(within(result).getByText("final.mp4")).toBeTruthy();
    expect(api.render).toHaveBeenCalledWith("p1", "final");
    await userEvent.click(within(result).getByRole("button", { name: t("export.reveal") }));
    expect(api.revealExport).toHaveBeenCalledWith("p1", "final.mp4");
  });

  it("refuses an export name the server would reject", async () => {
    vi.mocked(api.projects).mockResolvedValue([item()]);
    vi.mocked(api.exports).mockResolvedValue([]);
    render(<ExportStep projectId="p1" />);

    const name = await screen.findByLabelText(t("export.name"));
    await userEvent.clear(name);
    await userEvent.type(name, "../final");

    expect(screen.getByText(t("export.name.invalid"))).toBeTruthy();
    expect(screen.getByRole("button", { name: t("export.render") })).toHaveProperty(
      "disabled",
      true,
    );
  });
});
