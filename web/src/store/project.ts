import type { Project } from "@powereditor/composition";
import { temporal } from "zundo";
import { create } from "zustand";

/** Edits of the same `group` closer together than this become one undo step. */
export const GROUP_WINDOW_MS = 1000;
export const HISTORY_LIMIT = 100;

export interface ProjectState {
  projectId: string | null;
  project: Project | null;
  etag: string | null;
  /** Bumped by every `load`, so watchers can tell a fresh load from an edit. */
  revision: number;
  /** Open a project with an empty history. */
  load: (projectId: string, project: Project, etag: string) => void;
  setEtag: (etag: string) => void;
  /**
   * Apply a pure edit (see `edit/operations.ts`). Edits that share a `group` key within
   * `GROUP_WINDOW_MS` of each other, like a burst of trims of one edge, undo as one step.
   */
  edit: (recipe: (project: Project) => Project, group?: string) => void;
  undo: () => void;
  redo: () => void;
}

interface StoreOptions {
  now?: () => number;
  historyLimit?: number;
}

/** The open project with undo/redo over `project` only (zundo); the ETag is not history. */
export function createProjectStore({
  now = Date.now,
  historyLimit = HISTORY_LIMIT,
}: StoreOptions = {}) {
  let lastGroup: { key: string; at: number } | null = null;

  const store = create<ProjectState>()(
    temporal(
      (set, get) => ({
        projectId: null,
        project: null,
        etag: null,
        revision: 0,
        load: (projectId, project, etag) => {
          set({ projectId, project, etag, revision: get().revision + 1 });
          lastGroup = null;
          store.temporal.getState().clear();
        },
        setEtag: (etag) => set({ etag }),
        edit: (recipe, group) => {
          const current = get().project;
          if (!current) return;
          const next = recipe(current);
          if (next === current) return;
          const at = now();
          const history = store.temporal.getState();
          const continues =
            group !== undefined && lastGroup?.key === group && at - lastGroup.at < GROUP_WINDOW_MS;
          lastGroup = group === undefined ? null : { key: group, at };
          if (!continues) {
            set({ project: next });
            return;
          }
          history.pause();
          set({ project: next });
          history.resume();
        },
        undo: () => {
          lastGroup = null;
          store.temporal.getState().undo();
        },
        redo: () => {
          lastGroup = null;
          store.temporal.getState().redo();
        },
      }),
      {
        partialize: (state) => ({ project: state.project }),
        equality: (past, current) => past.project === current.project,
        limit: historyLimit,
      },
    ),
  );
  return store;
}

export type ProjectStore = ReturnType<typeof createProjectStore>;

export const useProjectStore = createProjectStore();
