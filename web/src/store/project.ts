import type { Project } from "@powereditor/composition";
import { temporal } from "zundo";
import { create } from "zustand";

interface ProjectState {
  project: Project | null;
  etag: string | null;
  load: (project: Project, etag: string) => void;
}

/** The open project. `temporal` records edits for undo/redo, wired to the editor in Phase 7. */
export const useProjectStore = create<ProjectState>()(
  temporal(
    (set) => ({
      project: null,
      etag: null,
      load: (project, etag) => set({ project, etag }),
    }),
    { partialize: (state) => ({ project: state.project }) },
  ),
);
