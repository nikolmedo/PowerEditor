import type { Project } from "@powereditor/composition";
import { ApiError } from "../api/client";
import type { ProjectStore } from "../store/project";

export const AUTOSAVE_DELAY_MS = 800;

/** `conflict`: the file changed elsewhere; saving stops until the user picks a version. */
export type SaveStatus = "saved" | "pending" | "saving" | "conflict" | "error";

export type SaveProject = (
  projectId: string,
  project: Project,
  etag: string,
  options?: { keepalive?: boolean },
) => Promise<string>;

interface AutosaveOptions {
  save: SaveProject;
  onStatus: (status: SaveStatus, error?: unknown) => void;
  delayMs?: number;
}

export interface Autosave {
  /** Save pending edits now; `keepalive` lets the request outlive a closing page. */
  flush: (options?: { keepalive?: boolean }) => Promise<void>;
  /** Resolve a conflict in favor of the open project, saving it over the given ETag. */
  overwrite: (etag: string) => Promise<void>;
  dispose: () => void;
}

/**
 * Debounced `PUT` of every edit of the store's project. A save sends the ETag the project was
 * loaded or last saved with; an edit made while a save runs is saved right after it.
 */
export function startAutosave(
  store: ProjectStore,
  { save, onStatus, delayMs = AUTOSAVE_DELAY_MS }: AutosaveOptions,
): Autosave {
  let saved = store.getState().project;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let running: Promise<void> | null = null;
  let status: SaveStatus = "saved";

  const report = (next: SaveStatus, error?: unknown) => {
    if (next === status && error === undefined) return;
    status = next;
    onStatus(next, error);
  };
  const cancel = () => {
    if (timer !== null) clearTimeout(timer);
    timer = null;
  };
  const schedule = () => {
    cancel();
    timer = setTimeout(() => void run(), delayMs);
  };

  const run = async (options?: { keepalive?: boolean }): Promise<void> => {
    cancel();
    if (running) {
      await running;
      return run(options);
    }
    const { projectId, project, etag, revision } = store.getState();
    if (!projectId || !project || etag === null || project === saved) return;
    report("saving");
    running = (async () => {
      try {
        const next = await save(projectId, project, etag, {
          keepalive: options?.keepalive ?? false,
        });
        // A project loaded while this save ran has its own ETag: never stamp it with ours.
        if (store.getState().revision !== revision) return;
        store.getState().setEtag(next);
        saved = project;
        if (store.getState().project === saved) report("saved");
        else schedule();
      } catch (error) {
        const conflict = error instanceof ApiError && error.code === "revision_conflict";
        report(conflict ? "conflict" : "error", error);
      }
    })();
    await running;
    running = null;
  };

  const unsubscribe = store.subscribe((state, previous) => {
    if (state.revision !== previous.revision) {
      cancel();
      saved = state.project;
      report("saved");
      return;
    }
    if (state.project === previous.project || status === "conflict") return;
    if (state.project === saved) {
      cancel();
      if (status === "pending") report("saved");
      return;
    }
    if (status !== "saving") report("pending");
    schedule();
  });

  return {
    flush: (options) => run(options),
    overwrite: async (etag) => {
      store.getState().setEtag(etag);
      report("pending");
      await run();
    },
    dispose: () => {
      cancel();
      unsubscribe();
    },
  };
}
