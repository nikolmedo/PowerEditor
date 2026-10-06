import { useEffect, useRef, useState } from "react";
import { api } from "../api/endpoints";
import { startAutosave, type Autosave, type SaveStatus } from "../edit/autosave";
import { useProjectStore } from "../store/project";

export interface AutosaveState {
  status: SaveStatus;
  error: unknown;
  /** Save now (the retry after an error). */
  flush: () => void;
  /** Resolve a conflict by saving the open project over the latest stored one. */
  keepMine: () => Promise<void>;
}

/** Autosave of the open project while the review step is mounted; pending edits are flushed
 * when the step unmounts and, with a keepalive request, when the page is closed. */
export function useAutosave(projectId: string): AutosaveState {
  const [state, setState] = useState<{ status: SaveStatus; error: unknown }>({
    status: "saved",
    error: null,
  });
  const autosave = useRef<Autosave | null>(null);

  useEffect(() => {
    const started = startAutosave(useProjectStore, {
      save: api.saveProject,
      onStatus: (status, error) => setState({ status, error: error ?? null }),
    });
    autosave.current = started;
    const leave = () => void started.flush({ keepalive: true });
    window.addEventListener("pagehide", leave);
    return () => {
      window.removeEventListener("pagehide", leave);
      void started.flush();
      started.dispose();
    };
  }, []);

  return {
    ...state,
    flush: () => void autosave.current?.flush(),
    keepMine: async () => {
      let etag: string;
      try {
        ({ etag } = await api.project(projectId));
      } catch (error) {
        // The conflict stays unresolved; retrying saves again and reports the conflict anew.
        setState({ status: "error", error });
        return;
      }
      await autosave.current?.overwrite(etag);
    },
  };
}
