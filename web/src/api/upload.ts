import { ApiError, parseError } from "./client";
import type { MusicFile, ProjectOptions } from "./types";

export type UploadState =
  | { phase: "idle" }
  | { phase: "uploading"; loaded: number; total: number }
  | { phase: "done" }
  | { phase: "failed"; error: ApiError };

export type UploadAction =
  | { type: "start"; total: number }
  | { type: "progress"; loaded: number; total: number }
  | { type: "done" }
  | { type: "failed"; error: ApiError };

export function uploadReducer(state: UploadState, action: UploadAction): UploadState {
  switch (action.type) {
    case "start":
      return { phase: "uploading", loaded: 0, total: action.total };
    case "progress":
      if (state.phase !== "uploading") return state;
      return { phase: "uploading", loaded: action.loaded, total: action.total };
    case "done":
      return { phase: "done" };
    case "failed":
      return { phase: "failed", error: action.error };
  }
}

export function uploadFraction(state: UploadState): number {
  if (state.phase === "done") return 1;
  if (state.phase !== "uploading" || state.total <= 0) return 0;
  return Math.min(1, state.loaded / state.total);
}

export interface Upload<T> {
  done: Promise<T>;
  abort: () => void;
}

/** POST a form with XHR instead of fetch, because only XHR reports upload progress. */
function postForm<T>(
  url: string,
  form: FormData,
  onProgress: (loaded: number, total: number) => void,
): Upload<T> {
  const xhr = new XMLHttpRequest();
  const done = new Promise<T>((resolve, reject) => {
    xhr.upload.onprogress = (event) => onProgress(event.loaded, event.total);
    xhr.onload = () => {
      let body: unknown = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        // A non-JSON answer still becomes an ApiError below.
      }
      if (xhr.status >= 200 && xhr.status < 300 && body) resolve(body as T);
      else reject(parseError(xhr.status, body));
    };
    xhr.onerror = () => reject(new ApiError(0, "network", "The local server is not reachable."));
    xhr.onabort = () => reject(new ApiError(0, "cancelled", "The upload was cancelled."));
  });
  xhr.open("POST", url);
  xhr.send(form);
  return { done, abort: () => xhr.abort() };
}

/** Create a project from local files with `POST /api/projects/upload`. */
export function uploadProject(
  files: readonly File[],
  options: ProjectOptions,
  onProgress: (loaded: number, total: number) => void,
): Upload<{ id: string }> {
  const form = new FormData();
  for (const file of files) form.append("files", file, file.name);
  for (const [key, value] of Object.entries(options)) {
    if (value) form.append(key, value);
  }
  return postForm("/api/projects/upload", form, onProgress);
}

/** Store a music file in the project's media folder; adding it to the timeline is an edit. */
export function uploadMusic(
  projectId: string,
  file: File,
  onProgress: (loaded: number, total: number) => void,
): Upload<MusicFile> {
  const form = new FormData();
  form.append("file", file, file.name);
  return postForm(`/api/projects/${encodeURIComponent(projectId)}/music`, form, onProgress);
}
