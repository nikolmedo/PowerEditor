import { describe, expect, it } from "vitest";

import { edgeFadeFrames, edgeFadeGain } from "../src/clips/edgeFade";

describe("edgeFadeFrames", () => {
  it("converts milliseconds to whole frames", () => {
    expect(edgeFadeFrames(100, 30)).toBe(3);
    expect(edgeFadeFrames(200, 25)).toBe(5);
  });

  it("keeps at least one frame for a sub-frame crossfade and none when disabled", () => {
    expect(edgeFadeFrames(15, 30)).toBe(1);
    expect(edgeFadeFrames(0, 30)).toBe(0);
  });
});

describe("edgeFadeGain", () => {
  it("ramps in and out symmetrically at the clip edges", () => {
    const gains = Array.from({ length: 10 }, (_, frame) => edgeFadeGain(frame, 10, 2));
    expect(gains).toEqual([0.25, 0.75, 1, 1, 1, 1, 1, 1, 0.75, 0.25]);
  });

  it("shortens the fade on clips shorter than two fades", () => {
    const gains = Array.from({ length: 3 }, (_, frame) => edgeFadeGain(frame, 3, 4));
    expect(gains).toEqual([0.5, 1, 0.5]);
  });

  it("is unity gain when the fade is disabled", () => {
    expect(edgeFadeGain(0, 10, 0)).toBe(1);
    expect(edgeFadeGain(9, 10, 0)).toBe(1);
  });
});
