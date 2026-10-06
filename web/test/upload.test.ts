import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../src/api/client";
import { uploadFraction, uploadProject, uploadReducer } from "../src/api/upload";

/** A stand-in XHR: records what was sent and lets each test decide how the request ends. */
class FakeXhr {
  static last: FakeXhr | null = null;
  upload: { onprogress: ((event: { loaded: number; total: number }) => void) | null } = {
    onprogress: null,
  };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;
  status = 0;
  responseText = "";
  opened: [string, string] | null = null;
  sent: FormData | null = null;

  constructor() {
    FakeXhr.last = this;
  }
  open(method: string, url: string) {
    this.opened = [method, url];
  }
  send(body: FormData) {
    this.sent = body;
  }
  abort() {
    this.onabort?.();
  }
  finish(status: number, body: string) {
    this.status = status;
    this.responseText = body;
    this.onload?.();
  }
}

function start() {
  vi.stubGlobal("XMLHttpRequest", FakeXhr);
  const progress = vi.fn();
  const file = new File(["abc"], "take 1.mp4");
  const upload = uploadProject([file], { preset: "reel_9x16", language: "" }, progress);
  const xhr = FakeXhr.last;
  if (!xhr) throw new Error("no request was made");
  return { upload, xhr, progress };
}

afterEach(() => vi.unstubAllGlobals());

describe("uploadProject", () => {
  it("posts the files with the non-empty options and reports progress", async () => {
    const { upload, xhr, progress } = start();
    expect(xhr.opened).toEqual(["POST", "/api/projects/upload"]);
    expect((xhr.sent?.get("files") as File).name).toBe("take 1.mp4");
    expect(xhr.sent?.get("preset")).toBe("reel_9x16");
    expect(xhr.sent?.has("language")).toBe(false);

    xhr.upload.onprogress?.({ loaded: 1, total: 3 });
    expect(progress).toHaveBeenCalledWith(1, 3);
    xhr.finish(201, '{"id":"p7"}');
    expect(await upload.done).toEqual({ id: "p7" });
  });

  it("turns an error answer into an ApiError", async () => {
    const { upload, xhr } = start();
    xhr.finish(422, '{"detail":{"code":"source_not_found","message":"missing"}}');
    await expect(upload.done).rejects.toMatchObject({ status: 422, code: "source_not_found" });
  });

  it("rejects with a cancelled error when aborted and a network error when unreachable", async () => {
    const aborted = start();
    aborted.upload.abort();
    await expect(aborted.upload.done).rejects.toMatchObject({ code: "cancelled" });
    const offline = start();
    offline.xhr.onerror?.();
    await expect(offline.upload.done).rejects.toBeInstanceOf(ApiError);
  });
});

describe("uploadReducer", () => {
  it("tracks progress only while uploading and ends on done or failure", () => {
    let state = uploadReducer({ phase: "idle" }, { type: "progress", loaded: 1, total: 2 });
    expect(state).toEqual({ phase: "idle" });
    state = uploadReducer(state, { type: "start", total: 4 });
    state = uploadReducer(state, { type: "progress", loaded: 1, total: 4 });
    expect(uploadFraction(state)).toBe(0.25);
    const error = new ApiError(0, "network", "offline");
    expect(uploadReducer(state, { type: "failed", error })).toEqual({ phase: "failed", error });
    expect(uploadFraction(uploadReducer(state, { type: "done" }))).toBe(1);
  });
});
