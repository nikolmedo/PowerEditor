import { describe, expect, it } from "vitest";
import {
  buildTimeline,
  clipAt,
  fileLabel,
  frameAtRatio,
  neighbourClip,
} from "../src/review/timelineModel";
import { PROJECT } from "./fixtures/reviewProject";

describe("buildTimeline", () => {
  const model = buildTimeline(PROJECT, 0.8);

  it("places kept clips back to back in their source color", () => {
    expect(model.durationInFrames).toBe(105);
    expect(model.video.map((c) => [c.clipId, c.startFrame, c.durationInFrames, c.color])).toEqual([
      ["k1", 0, 60, "#111111"],
      ["k2", 60, 30, "#222222"],
      ["k3", 90, 15, "#111111"],
    ]);
  });

  it("badges alternatives and flags low-confidence decisions", () => {
    expect(model.video.map((c) => [c.takes, c.lowConfidence])).toEqual([
      [2, true],
      [0, false],
      [0, false],
    ]);
  });

  it("anchors removed clips at the cut where they were dropped", () => {
    expect(model.removed.map((c) => [c.clipId, c.startFrame, c.removed])).toEqual([
      ["r1", 60, true],
      ["r2", 90, true],
    ]);
  });

  it("lists which file is used for how long, and the other tracks", () => {
    expect(model.legend).toEqual([
      { sourceId: "a", color: "#111111", label: "cam-a.mp4", seconds: 2.5 },
      { sourceId: "b", color: "#222222", label: "cam-b.MOV", seconds: 1 },
    ]);
    expect(model.subtitles).toEqual([{ startFrame: 0, endFrame: 35, text: "Hola mundo." }]);
    expect(model.graphics).toEqual([
      { id: "o1", startFrame: 0, endFrame: 30, templateId: "title" },
    ]);
    expect(model.music).toEqual([{ id: "m1", label: "song.mp3" }]);
  });
});

describe("timeline helpers", () => {
  const model = buildTimeline(PROJECT, 0.8);

  it("maps a click position to a frame inside the timeline", () => {
    expect(frameAtRatio(0.5, 105)).toBe(52);
    expect(frameAtRatio(1.4, 105)).toBe(104);
    expect(frameAtRatio(-1, 105)).toBe(0);
  });

  it("finds the kept clip under a frame", () => {
    expect(clipAt(model, 61)?.clipId).toBe("k2");
    expect(clipAt(model, 105)).toBeUndefined();
    expect(fileLabel("D:\\a\\b.mp4")).toBe("b.mp4");
  });

  it("walks the kept clips from the selection, a removed clip or either end", () => {
    const walk = (id: string | null, step: -1 | 1) => neighbourClip(model, id, step)?.clipId;
    expect([walk("k1", 1), walk("k2", -1), walk("k3", 1)]).toEqual(["k2", "k1", undefined]);
    // r2 was dropped at the cut before k3.
    expect([walk("r2", 1), walk("r2", -1)]).toEqual(["k3", "k2"]);
    expect([walk(null, 1), walk(null, -1)]).toEqual(["k1", "k3"]);
  });
});
