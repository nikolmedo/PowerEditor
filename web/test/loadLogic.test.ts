import { describe, expect, it } from "vitest";
import { ApiError } from "../src/api/client";
import { uploadFraction, uploadReducer, type UploadState } from "../src/api/upload";
import { projectStatus } from "../src/shell/projectStatus";
import { errorAction } from "../src/steps/errorActions";
import type { ProjectListItem } from "../src/api/types";

describe("uploadReducer", () => {
  it("tracks bytes sent and ends done or failed", () => {
    let state: UploadState = { phase: "idle" };
    state = uploadReducer(state, { type: "start", total: 400 });
    state = uploadReducer(state, { type: "progress", loaded: 100, total: 400 });
    expect(uploadFraction(state)).toBe(0.25);

    const failed = uploadReducer(state, { type: "failed", error: new ApiError(0, "network", "") });
    expect(failed.phase).toBe("failed");
    expect(uploadFraction(uploadReducer(state, { type: "done" }))).toBe(1);
  });

  it("ignores progress that arrives after the upload ended", () => {
    const done = uploadReducer({ phase: "uploading", loaded: 1, total: 2 }, { type: "done" });
    expect(uploadReducer(done, { type: "progress", loaded: 1, total: 2 })).toBe(done);
    expect(uploadFraction({ phase: "uploading", loaded: 0, total: 0 })).toBe(0);
  });
});

describe("errorAction", () => {
  it("points each fixable failure at the screen that fixes it", () => {
    expect(errorAction("missing_openai_key")).toEqual({
      to: "/settings",
      label: "action.settings",
    });
    expect(errorAction("missing_ffmpeg")).toEqual({ to: "/setup", label: "action.setup" });
    expect(errorAction("missing_node")).toEqual({ to: "/setup", label: "action.setup" });
    expect(errorAction("provider_unauthorized")).toEqual({
      to: "/settings/providers",
      label: "action.providers",
    });
    expect(errorAction("render_timeout")).toBeNull();
    expect(errorAction(null)).toBeNull();
  });
});

const item = (overrides: Partial<ProjectListItem>): ProjectListItem => ({
  id: "p1",
  name: "Demo",
  createdAt: "2026-10-06T10:00:00Z",
  status: "created",
  durationSeconds: null,
  thumbnailUrl: null,
  activeJobId: null,
  activeJobKind: null,
  lastError: null,
  ...overrides,
});

describe("projectStatus", () => {
  it("prefers a running job, then a failure, then the stored state", () => {
    const error = { code: "ffmpeg_failed", message: "x" };
    expect(
      projectStatus(item({ activeJobId: "j", activeJobKind: "analyze", lastError: error })),
    ).toBe("analyzing");
    expect(
      projectStatus(item({ status: "analyzed", activeJobId: "j", activeJobKind: "render" })),
    ).toBe("rendering");
    expect(projectStatus(item({ status: "analyzed", lastError: error }))).toBe("error");
    expect(projectStatus(item({ status: "analyzed" }))).toBe("ready");
    expect(projectStatus(item({ status: "ingested" }))).toBe("created");
  });
});
