import { describe, expect, it } from "vitest";

import type { Clip, Project } from "../src/types";
import { clipFrames, roundHalfEven, timelineLayout } from "../src/timeline";
import fixture from "./fixtures/project.json";

const project = fixture.project as Project;

function clipWith(overrides: Partial<Clip>): Clip {
  const base = project.clips[0];
  if (base === undefined) throw new Error("fixture has no clips");
  return { ...base, ...overrides };
}

describe("roundHalfEven", () => {
  it("rounds exact halves to the even neighbour like Python's round()", () => {
    expect([0.5, 1.5, 2.5, 34.5, 37.5, -1.5].map(roundHalfEven)).toEqual([0, 2, 2, 34, 38, -2]);
  });

  it("rounds non-halves to the nearest integer", () => {
    expect(
      [1.4999, 1.5000000000000013, 19.499999999999996, 88.00000000000004].map(roundHalfEven),
    ).toEqual([1, 2, 19, 88]);
  });
});

describe("clipFrames", () => {
  it("divides the source span by speed before converting to frames", () => {
    expect(clipFrames(clipWith({ inSec: 4, outSec: 5, speed: 1.5 }), 30)).toBe(20);
    expect(clipFrames(clipWith({ inSec: 7.1, outSec: 9.3, speed: 0.75 }), 30)).toBe(88);
  });

  it("uses the backend's half-to-even rounding on exact half frames", () => {
    expect(clipFrames(clipWith({ inSec: 0, outSec: 1.15, speed: 1 }), 30)).toBe(34);
  });
});

describe("timelineLayout", () => {
  it("matches the layout the backend computes for the shared fixture", () => {
    expect(timelineLayout(project)).toEqual(fixture.expected);
  });

  it("is empty when every clip is removed", () => {
    const allRemoved = {
      ...project,
      clips: project.clips.map((clip) => ({ ...clip, removed: true })),
    };
    expect(timelineLayout(allRemoved)).toEqual({ durationInFrames: 0, clips: [] });
  });
});
