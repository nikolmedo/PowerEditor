import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { translate } from "../src/i18n";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { MusicFile } from "../src/api/types";
import { uploadMusic, type Upload } from "../src/api/upload";
import { musicTrack } from "../src/edit/audio";
import { AudioPanel } from "../src/review/AudioPanel";
import { useProjectStore } from "../src/store/project";
import { PROJECT } from "./fixtures/reviewProject";

const t = (key: Parameters<typeof translate>[1]) => translate("es", key);

vi.mock("../src/api/upload", async (importActual) => ({
  ...(await importActual<typeof import("../src/api/upload")>()),
  uploadMusic: vi.fn(),
}));

/** An upload whose answer the test decides. */
function deferredUpload() {
  let resolve: (file: MusicFile) => void = () => undefined;
  let reject: (error: unknown) => void = () => undefined;
  const done = new Promise<MusicFile>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  const abort = vi.fn(() => reject(new Error("aborted")));
  const upload: Upload<MusicFile> = { done, abort };
  const finish = (fileName: string) => resolve({ fileName, durationSeconds: 1, url: "" });
  return { upload, finish, abort };
}

const pick = (name: string) =>
  userEvent.upload(
    screen.getByLabelText("Reemplazar…", { selector: "input" }),
    new File(["x"], name, { type: "audio/mpeg" }),
  );

const currentMusic = () => {
  const project = useProjectStore.getState().project;
  return project ? musicTrack(project)?.sourcePath : undefined;
};

describe("AudioPanel music upload", () => {
  beforeEach(() => {
    useProjectStore.getState().load("p1", PROJECT, "etag");
    vi.mocked(uploadMusic).mockReset();
  });

  it("keeps the newest upload when an older one finishes later", async () => {
    const first = deferredUpload();
    const second = deferredUpload();
    vi.mocked(uploadMusic).mockReturnValueOnce(first.upload).mockReturnValueOnce(second.upload);
    render(<AudioPanel projectId="p1" project={PROJECT} />);

    await pick("one.mp3");
    await pick("two.mp3");
    await act(async () => second.finish("music-two.mp3"));
    await act(async () => first.finish("music-one.mp3"));

    expect(first.abort).toHaveBeenCalled();
    expect(currentMusic()).toBe("music-two.mp3");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("does not touch another project opened while the upload ran", async () => {
    const pending = deferredUpload();
    vi.mocked(uploadMusic).mockReturnValueOnce(pending.upload);
    render(<AudioPanel projectId="p1" project={PROJECT} />);

    await pick("one.mp3");
    act(() => useProjectStore.getState().load("p2", PROJECT, "etag"));
    await act(async () => pending.finish("music-one.mp3"));

    expect(useProjectStore.getState().projectId).toBe("p2");
    expect(currentMusic()).toBe("C:/music/song.mp3");
    // The dropped upload must not leave its progress bar behind.
    expect(screen.queryByRole("progressbar")).toBeNull();
  });

  it("clears the progress of an upload that fails after another project was opened", async () => {
    const pending = deferredUpload();
    vi.mocked(uploadMusic).mockReturnValueOnce(pending.upload);
    render(<AudioPanel projectId="p1" project={PROJECT} />);

    await pick("one.mp3");
    expect(screen.getByRole("progressbar")).toBeTruthy();
    act(() => useProjectStore.getState().load("p2", PROJECT, "etag"));
    await act(async () => pending.abort());

    expect(screen.queryByRole("progressbar")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("AudioPanel track focus and mute", () => {
  const stored = () => useProjectStore.getState().project;
  const trackOf = (id: string) => stored()?.audioTracks.find((track) => track.id === id);

  beforeEach(() => useProjectStore.getState().load("p1", PROJECT, "etag"));

  it("mutes the voice and the music from their own sections", async () => {
    const user = userEvent.setup();
    render(<AudioPanel projectId="p1" project={PROJECT} />);

    const voice = screen.getByRole("region", { name: t("audio.voice") });
    await user.click(within(voice).getByRole("checkbox", { name: t("audio.mute") }));
    expect(trackOf("voice")?.muted).toBe(true);
    expect(trackOf("m1")?.muted).toBeUndefined();

    const music = screen.getByRole("region", { name: t("audio.music") });
    await user.click(within(music).getByRole("checkbox", { name: t("audio.mute") }));
    expect(trackOf("m1")?.muted).toBe(true);
  });

  it("highlights the focused track and sets the selected clip's level from the voice", () => {
    const clip = PROJECT.clips.find((candidate) => candidate.id === "k2") ?? null;
    render(<AudioPanel projectId="p1" project={PROJECT} focusTrack="voice" clip={clip} />);

    const voice = screen.getByRole("region", { name: t("audio.voice") });
    expect(voice.hasAttribute("data-focused")).toBe(true);
    expect(
      screen.getByRole("region", { name: t("audio.music") }).hasAttribute("data-focused"),
    ).toBe(false);
    const level = within(voice).getByRole("slider", { name: new RegExp(t("audio.clipLevel")) });
    fireEvent.change(level, { target: { value: "0.5" } });
    expect(stored()?.clips.find((candidate) => candidate.id === "k2")?.volume).toBe(0.5);
  });

  it("shows no clip level without a selected clip or when the music is focused", () => {
    const clip = PROJECT.clips[0] ?? null;
    const { rerender } = render(<AudioPanel projectId="p1" project={PROJECT} focusTrack="voice" />);
    expect(screen.queryByText(t("audio.clipLevel"))).toBeNull();
    rerender(<AudioPanel projectId="p1" project={PROJECT} focusTrack="music" clip={clip} />);
    expect(screen.queryByText(t("audio.clipLevel"))).toBeNull();
    expect(
      screen.getByRole("region", { name: t("audio.music") }).hasAttribute("data-focused"),
    ).toBe(true);
  });
});
