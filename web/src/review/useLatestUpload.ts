import { useCallback, useReducer, useRef, useState } from "react";
import { uploadReducer, type Upload, type UploadState } from "../api/upload";
import { useProjectStore } from "../store/project";

type StartUpload<T> = (
  projectId: string,
  file: File,
  onProgress: (loaded: number, total: number) => void,
) => Upload<T>;

export interface LatestUpload {
  state: UploadState;
  error: unknown;
  /** Upload `file`, then hand the stored file to `onStored`, unless a newer upload started or
   * another project was opened in the meantime. */
  send: (file: File) => Promise<void>;
}

/**
 * Uploads into a project where only the newest one counts: starting an upload aborts the one
 * before it, and an upload that finishes after a newer one started, or after the editor moved
 * to another project, is dropped instead of editing the wrong state.
 */
export function useLatestUpload<T>(
  projectId: string,
  start: StartUpload<T>,
  onStored: (stored: T) => void,
): LatestUpload {
  const [state, dispatch] = useReducer(uploadReducer, { phase: "idle" });
  const [error, setError] = useState<unknown>(null);
  const latest = useRef(0);
  const active = useRef<Upload<T> | null>(null);

  const send = useCallback(
    async (file: File) => {
      const token = ++latest.current;
      active.current?.abort();
      const isCurrent = () =>
        token === latest.current && useProjectStore.getState().projectId === projectId;
      setError(null);
      dispatch({ type: "start", total: file.size });
      const upload = start(projectId, file, (loaded, total) => {
        if (isCurrent()) dispatch({ type: "progress", loaded, total });
      });
      active.current = upload;
      try {
        const stored = await upload.done;
        if (!isCurrent()) return;
        dispatch({ type: "done" });
        onStored(stored);
      } catch (caught) {
        if (!isCurrent()) return;
        setError(caught);
        dispatch({ type: "done" });
      } finally {
        if (active.current === upload) active.current = null;
      }
    },
    [projectId, start, onStored],
  );

  return { state, error, send };
}
