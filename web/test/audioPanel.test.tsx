import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { MusicFile } from "../src/api/types";
import { uploadMusic, type Upload } from "../src/api/upload";
import { musicTrack } from "../src/edit/audio";
import { AudioPanel } from "../src/review/AudioPanel";
import { useProjectStore } from "../src/store/project";
import { PROJECT } from "./fixtures/reviewProject";

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
  });
});
