import { describe, expect, it } from "vitest";
import type { JobEvent } from "../src/api/types";
import { initialProgress, reduceJob, stageFamily, stageRows } from "../src/jobs/jobProgress";

const event = (overrides: Partial<JobEvent>): JobEvent => ({
  jobId: "j1",
  status: "running",
  stage: null,
  fraction: 0,
  message: "",
  error: null,
  result: null,
  ...overrides,
});

function replay(events: Partial<JobEvent>[]) {
  return events.reduce((state, next) => reduceJob(state, event(next)), initialProgress("j1"));
}

describe("stageFamily", () => {
  it("drops the per-source suffix but keeps hyphenated stage names", () => {
    expect(stageFamily("vad-s1")).toBe("vad");
    expect(stageFamily("ingest-cam-a")).toBe("ingest");
    expect(stageFamily("final-pass")).toBe("final-pass");
    expect(stageFamily("takes")).toBe("takes");
  });
});

describe("reduceJob", () => {
  it("marks a stage done when the next one starts", () => {
    const state = replay([
      { stage: "ingest-s1", fraction: 0.5 },
      { stage: "transcribe-s1", fraction: 0.1 },
    ]);
    expect(stageRows(state, "analyze").slice(0, 3)).toEqual([
      { stage: "ingest", state: "done", fraction: 1 },
      { stage: "transcribe", state: "active", fraction: 0.1 },
      { stage: "vad", state: "pending", fraction: 0 },
    ]);
  });

  it("ignores events of another job and anything after the end", () => {
    const ended = replay([{ stage: "render", fraction: 0.4 }, { status: "cancelled" }]);
    const after = reduceJob(ended, event({ stage: "render", fraction: 0.9 }));
    const foreign = reduceJob(initialProgress("j1"), event({ jobId: "j2", fraction: 0.5 }));

    expect(after).toBe(ended);
    expect(foreign).toEqual(initialProgress("j1"));
  });

  it("completes every stage on success and keeps the result", () => {
    const state = replay([
      { stage: "audio", fraction: 1 },
      { status: "succeeded", fraction: 1, result: { file: "final.mp4" } },
    ]);
    expect(stageRows(state, "render").map((row) => row.state)).toEqual(["done", "done", "done"]);
    expect(state.result).toEqual({ file: "final.mp4" });
  });

  it("keeps the failing stage and its error", () => {
    const state = replay([
      { stage: "render", fraction: 0.3 },
      { status: "failed", stage: "render", error: { code: "render_timeout", message: "slow" } },
    ]);
    expect(stageRows(state, "render")[1]).toEqual({
      stage: "render",
      state: "failed",
      fraction: 0.3,
    });
    expect(state.error?.code).toBe("render_timeout");
  });
});
