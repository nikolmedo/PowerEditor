import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { forwardRef, useImperativeHandle } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../src/api/client";
import { api } from "../src/api/endpoints";
import { watchJob } from "../src/api/jobs";
import { uploadMusic } from "../src/api/upload";
import type { JobEvent, JobInfo, ProjectListItem } from "../src/api/types";
import { translate, type MessageKey } from "../src/i18n";
import { ReviewStep } from "../src/review/ReviewStep";
import { ProjectsHome } from "../src/shell/ProjectsHome";
import { ExportStep } from "../src/steps/ExportStep";
import { LoadStep } from "../src/steps/LoadStep";
import { useAppStore } from "../src/store/app";
import type { Project } from "@powereditor/composition";
import fixture from "../../packages/composition/test/fixtures/subtitles.json";
import { useProjectStore } from "../src/store/project";
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
      "saveProject",
      "render",
      "exportSubtitles",
      "exports",
      "revealExport",
      "cancelJob",
    ].map((name) => [name, vi.fn()]),
  ),
}));
vi.mock("../src/api/jobs", () => ({ watchJob: vi.fn(() => () => undefined) }));
vi.mock("../src/api/upload", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../src/api/upload")>()),
  uploadMusic: vi.fn(),
}));

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
    runtimes: [],
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

  it("opens the new project and says why processing could not start", async () => {
    vi.mocked(api.createProject).mockResolvedValue({ id: "p9" });
    vi.mocked(api.analyze).mockRejectedValue(new ApiError(409, "job_active", "busy"));
    vi.mocked(api.projects).mockResolvedValue([item({ id: "p9", status: "ingested" })]);
    const { rerender } = render(<LoadStep projectId={null} />);

    await userEvent.click(screen.getByRole("tab", { name: t("load.mode.paths") }));
    await userEvent.type(screen.getByLabelText(t("load.paths")), "C:/rec/a.mp4");
    await userEvent.click(screen.getByRole("button", { name: t("load.process") }));
    await waitFor(() => expect(useAppStore.getState().path).toBe("/projects/p9/load"));
    rerender(<LoadStep projectId="p9" />);

    expect(await screen.findByText(t("error.job_active"))).toBeTruthy();
    expect(screen.getByRole("button", { name: t("load.process") })).toBeTruthy();
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
    // Forget the project a previous test left open, so each test waits for its own load.
    useProjectStore.getState().load("none", PROJECT, "");
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

  const clipOf = (id: string) =>
    useProjectStore.getState().project?.clips.find((clip) => clip.id === id);
  const open = async (project: Project = PROJECT) => {
    vi.mocked(api.project).mockResolvedValue({ project, etag: '"e1"' });
    render(<ReviewStep projectId="p1" />);
    await screen.findByRole("tablist", { name: t("panel.label") });
  };

  it("removes, trims and undoes from the keyboard, then autosaves", async () => {
    vi.mocked(api.saveProject).mockResolvedValue('"e2"');
    await open();
    await userEvent.click(
      screen.getByRole("button", { name: t("review.clipAt", { time: "0:02.0" }) }),
    );

    await userEvent.keyboard("[[[[");
    expect(screen.getByText("0.20 s")).toBeTruthy();
    await userEvent.keyboard("{Delete}");
    expect(clipOf("k2")?.removed).toBe(true);
    // r1, k2 and r2 now all sit at the cut before k3.
    expect(
      screen.getAllByRole("button", { name: t("edit.removedAt", { time: "0:02.0" }) }),
    ).toHaveLength(3);
    await userEvent.keyboard("{Control>}z{/Control}");
    expect(clipOf("k2")?.removed).toBe(false);
    await userEvent.keyboard("{Control>}z{/Control}");
    expect(clipOf("k2")?.inSec).toBe(0);
    await userEvent.keyboard("{ArrowRight}{Delete}");
    expect(clipOf("k3")?.removed).toBe(true);

    await waitFor(() => expect(api.saveProject).toHaveBeenCalled(), { timeout: 2000 });
    const [id, saved, etag] = vi.mocked(api.saveProject).mock.calls[0] ?? [];
    expect([id, etag]).toEqual(["p1", '"e1"']);
    expect(saved?.clips.find((clip) => clip.id === "k3")?.removed).toBe(true);
    expect(await screen.findByText(t("save.saved"))).toBeTruthy();
  });

  it("switches takes from the clip panel and from an alt-click", async () => {
    await open();
    await userEvent.click(screen.getByText(t("review.takes", { count: 2 })));
    const takes = screen.getByRole("region", { name: t("edit.takes") });
    await userEvent.click(within(takes).getByRole("button", { name: t("edit.useTake") }));
    expect([clipOf("r1")?.removed, clipOf("k1")?.removed]).toEqual([false, true]);

    const user = userEvent.setup();
    await user.keyboard("{Alt>}");
    await user.click(screen.getByRole("button", { name: t("review.clipAt", { time: "0:00.0" }) }));
    await user.keyboard("{/Alt}");
    expect([clipOf("r1")?.removed, clipOf("k1")?.removed]).toEqual([true, false]);
  });

  it("changes one transition and applies a preset to every cut", async () => {
    await open();
    await userEvent.click(
      screen.getByRole("button", { name: t("review.clipAt", { time: "0:02.0" }) }),
    );
    await userEvent.click(screen.getByRole("tab", { name: t("panel.transitions") }));
    await userEvent.selectOptions(screen.getByLabelText(t("review.transition")), "slide");
    expect(clipOf("k2")?.transitionIn).toEqual({ type: "slide", durationFrames: 9 });

    await userEvent.selectOptions(screen.getByLabelText(t("edit.preset")), "punch_in");
    await userEvent.click(screen.getByRole("button", { name: t("edit.applyToAll") }));
    expect([clipOf("k2")?.transitionIn.type, clipOf("k3")?.transitionIn.type]).toEqual([
      "punch_in",
      "punch_in",
    ]);
  });

  it("edits a subtitle line and its style", async () => {
    await open(fixture.project as Project);
    await userEvent.click(screen.getByRole("tab", { name: t("panel.subtitles") }));
    const line = screen.getByDisplayValue("Ahora Esto va");
    await userEvent.clear(line);
    await userEvent.type(line, "Ahora esto vuela{enter}");
    const words = useProjectStore.getState().project?.subtitles.words ?? [];
    expect(words.slice(3, 6).map((word) => word.text)).toEqual(["Ahora", "esto", "vuela"]);

    await userEvent.selectOptions(screen.getByLabelText(t("edit.position")), "top");
    expect(useProjectStore.getState().project?.subtitles.style.position).toBe("top");
  });

  it("sets track levels, ducking and source matching from the audio panel", async () => {
    await open();
    await userEvent.click(screen.getByRole("tab", { name: t("panel.audio") }));
    const voice = screen.getByRole("region", { name: t("audio.voice") });
    const music = screen.getByRole("region", { name: t("audio.music") });
    const trackOf = (id: string) =>
      useProjectStore.getState().project?.audioTracks.find((track) => track.id === id);

    fireEvent.change(within(voice).getByLabelText(t("edit.volume"), { exact: false }), {
      target: { value: "0.5" },
    });
    expect(trackOf("voice")?.volume).toBe(0.5);
    await userEvent.click(within(voice).getByLabelText(t("audio.normalize")));
    expect(useProjectStore.getState().project?.normalizeSources).toBe(true);

    expect(within(music).getByText("song.mp3")).toBeTruthy();
    await userEvent.click(within(music).getByLabelText(t("audio.duck")));
    expect(trackOf("m1")?.duckingEnabled).toBe(false);
    await userEvent.click(within(music).getByRole("button", { name: t("audio.removeMusic") }));
    expect(trackOf("m1")).toBeUndefined();
    expect(within(music).getByText(t("audio.noMusic"))).toBeTruthy();
  });

  it("uploads a music file and puts it on the timeline", async () => {
    vi.mocked(uploadMusic).mockImplementation((_id, _file, onProgress) => {
      onProgress(1, 2);
      return {
        done: Promise.resolve({ fileName: "music-0a1b2c3d.mp3", durationSeconds: 3, url: "/m" }),
        abort: () => undefined,
      };
    });
    await open({ ...PROJECT, audioTracks: PROJECT.audioTracks.slice(0, 1) });
    await userEvent.click(screen.getByRole("tab", { name: t("panel.audio") }));

    await userEvent.upload(
      screen.getByLabelText(t("audio.addMusic")),
      new File(["abc"], "song.mp3", { type: "audio/mpeg" }),
    );

    await waitFor(() =>
      expect(useProjectStore.getState().project?.audioTracks.at(-1)?.sourcePath).toBe(
        "music-0a1b2c3d.mp3",
      ),
    );
    expect(vi.mocked(uploadMusic).mock.calls[0]?.[0]).toBe("p1");
  });

  it("grades every clip or only the selected one from the color panel", async () => {
    await open({
      ...PROJECT,
      sources: PROJECT.sources.map((source, index) =>
        index === 0
          ? { ...source, colorCorrection: { redGain: 1.1, greenGain: 1, blueGain: 0.9 } }
          : source,
      ),
    });
    await userEvent.click(screen.getByRole("tab", { name: t("panel.color") }));
    const state = () => useProjectStore.getState().project;

    await userEvent.click(screen.getByRole("button", { name: t("color.preset.warm") }));
    expect(state()?.colorGrade.preset).toBe("warm");
    fireEvent.change(screen.getByLabelText(t("color.brightness"), { exact: false }), {
      target: { value: "1.2" },
    });
    expect(state()?.colorGrade.brightness).toBe(1.2);

    await userEvent.click(
      screen.getByRole("button", { name: t("review.clipAt", { time: "0:02.0" }) }),
    );
    await userEvent.click(screen.getByRole("tab", { name: t("color.scope.clip") }));
    await userEvent.click(screen.getByRole("button", { name: t("color.preset.bw") }));
    expect(state()?.clips.find((clip) => clip.id === "k2")?.colorOverride?.saturation).toBe(0);
    expect(state()?.colorGrade.preset).toBe("warm");

    await userEvent.click(screen.getByRole("tab", { name: t("color.scope.all") }));
    await userEvent.click(screen.getByRole("button", { name: t("color.applyToAll") }));
    expect(state()?.clips.every((clip) => clip.colorOverride == null)).toBe(true);

    const match = screen.getByRole("region", { name: t("color.match") });
    await userEvent.click(within(match).getByRole("button", { name: t("color.reset") }));
    expect(state()?.sources[0]?.colorCorrection).toBeNull();
  });

  it("offers to reload or keep the open version after a conflicting save", async () => {
    vi.mocked(api.saveProject)
      .mockRejectedValueOnce(new ApiError(409, "revision_conflict", "changed"))
      .mockResolvedValueOnce('"e4"');
    await open();
    await userEvent.click(
      screen.getByRole("button", { name: t("review.clipAt", { time: "0:02.0" }) }),
    );
    await userEvent.keyboard("{Delete}");

    expect(await screen.findByText(t("save.conflictHint"), {}, { timeout: 2000 })).toBeTruthy();
    vi.mocked(api.project).mockResolvedValue({ project: PROJECT, etag: '"e3"' });
    await userEvent.click(screen.getByRole("button", { name: t("save.keepMine") }));

    await waitFor(() => expect(api.saveProject).toHaveBeenCalledTimes(2));
    expect(vi.mocked(api.saveProject).mock.calls[1]?.[2]).toBe('"e3"');
    expect(vi.mocked(api.saveProject).mock.calls[1]?.[1].clips[2]?.removed).toBe(true);
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
    expect(api.render).toHaveBeenCalledWith("p1", "final", "standard");
    await userEvent.click(within(result).getByRole("button", { name: t("export.reveal") }));
    expect(api.revealExport).toHaveBeenCalledWith("p1", "final.mp4");
  });

  it("renders a quick draft when the draft quality is picked", async () => {
    vi.mocked(api.projects).mockResolvedValue([item()]);
    vi.mocked(api.exports).mockResolvedValue([]);
    vi.mocked(api.render).mockResolvedValue(job({ id: "job-3", kind: "render" }));
    render(<ExportStep projectId="p1" />);

    await userEvent.selectOptions(
      await screen.findByLabelText(t("export.quality")),
      t("export.quality.draft"),
    );
    expect(screen.getByText(t("export.quality.draft.hint"))).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: t("export.render") }));

    expect(api.render).toHaveBeenCalledWith("p1", "final", "draft");
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
