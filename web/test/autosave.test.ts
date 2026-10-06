import type { Project } from "@powereditor/composition";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../src/api/client";
import { setRemoved } from "../src/edit/operations";
import { startAutosave, type SaveStatus } from "../src/edit/autosave";
import { createProjectStore } from "../src/store/project";
import { PROJECT } from "./fixtures/reviewProject";

type Save = (
  projectId: string,
  project: Project,
  etag: string,
  options?: { keepalive?: boolean },
) => Promise<string>;

function setup(save: Save) {
  const store = createProjectStore();
  store.getState().load("p1", PROJECT, '"e1"');
  const statuses: SaveStatus[] = [];
  const autosave = startAutosave(store, { save, delayMs: 800, onStatus: (s) => statuses.push(s) });
  const remove = (id: string) => store.getState().edit((p) => setRemoved(p, id, true));
  return { store, autosave, statuses, remove };
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("autosave", () => {
  it("saves once, 800 ms after the last of several edits, with the loaded ETag", async () => {
    const save = vi.fn<Save>().mockResolvedValue('"e2"');
    const { store, remove, statuses } = setup(save);
    remove("k2");
    await vi.advanceTimersByTimeAsync(500);
    remove("k3");
    await vi.advanceTimersByTimeAsync(799);
    expect(save).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);

    expect(save).toHaveBeenCalledTimes(1);
    expect(save).toHaveBeenCalledWith("p1", store.getState().project, '"e1"', { keepalive: false });
    expect(store.getState().etag).toBe('"e2"');
    expect(statuses.at(-1)).toBe("saved");
  });

  it("does not save after an undo back to the saved project", async () => {
    const save = vi.fn<Save>().mockResolvedValue('"e2"');
    const { store, remove, statuses } = setup(save);
    remove("k2");
    store.getState().undo();
    await vi.advanceTimersByTimeAsync(1000);
    expect(save).not.toHaveBeenCalled();
    expect(statuses.at(-1)).toBe("saved");
  });

  it("saves again when an edit lands while a save is running", async () => {
    let finish: (etag: string) => void = () => undefined;
    const save = vi
      .fn<Save>()
      .mockImplementationOnce(() => new Promise((resolve) => (finish = resolve)))
      .mockResolvedValueOnce('"e3"');
    const { store, remove } = setup(save);
    remove("k2");
    await vi.advanceTimersByTimeAsync(800);
    remove("k3");
    finish('"e2"');
    await vi.advanceTimersByTimeAsync(800);

    expect(save).toHaveBeenCalledTimes(2);
    expect(save.mock.calls[1]?.[2]).toBe('"e2"');
    expect(store.getState().etag).toBe('"e3"');
  });

  it("stops on a revision conflict until the user keeps their version", async () => {
    const save = vi
      .fn<Save>()
      .mockRejectedValueOnce(new ApiError(409, "revision_conflict", "changed"))
      .mockResolvedValueOnce('"e9"');
    const { store, remove, statuses, autosave } = setup(save);
    remove("k2");
    await vi.advanceTimersByTimeAsync(800);
    expect(statuses.at(-1)).toBe("conflict");

    remove("k3");
    await vi.advanceTimersByTimeAsync(2000);
    expect(save).toHaveBeenCalledTimes(1);

    await autosave.overwrite('"e5"');
    expect(save).toHaveBeenLastCalledWith("p1", store.getState().project, '"e5"', {
      keepalive: false,
    });
    expect(statuses.at(-1)).toBe("saved");
  });

  it("reports other failures as errors and retries on flush", async () => {
    const save = vi
      .fn<Save>()
      .mockRejectedValueOnce(new ApiError(409, "analysis_running", "busy"))
      .mockResolvedValueOnce('"e2"');
    const { remove, statuses, autosave } = setup(save);
    remove("k2");
    await vi.advanceTimersByTimeAsync(800);
    expect(statuses.at(-1)).toBe("error");

    await autosave.flush();
    expect(save).toHaveBeenCalledTimes(2);
    expect(statuses.at(-1)).toBe("saved");
  });

  it("flushes a pending edit at once and forgets a reloaded project", async () => {
    const save = vi.fn<Save>().mockResolvedValue('"e2"');
    const { store, remove, autosave } = setup(save);
    remove("k2");
    await autosave.flush();
    expect(save).toHaveBeenCalledTimes(1);

    remove("k3");
    store.getState().load("p1", PROJECT, '"e7"');
    await vi.advanceTimersByTimeAsync(1000);
    expect(save).toHaveBeenCalledTimes(1);
    autosave.dispose();
  });

  it("keeps the ETag of a project reloaded while a save was running", async () => {
    let finish: (etag: string) => void = () => undefined;
    const save = vi.fn<Save>(() => new Promise((resolve) => (finish = resolve)));
    const { store, remove, autosave } = setup(save);
    remove("k2");
    const flushed = autosave.flush();
    store.getState().load("p1", PROJECT, '"e8"');
    finish('"e2"');
    await flushed;
    expect(store.getState().etag).toBe('"e8"');
  });
});
