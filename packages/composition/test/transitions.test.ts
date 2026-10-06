import { describe, expect, it } from "vitest";

import { transitionStyle } from "../src/transitions/transitionStyle";

const PUNCH_IN = 1.1;

describe("transitionStyle", () => {
  it("leaves a cut untouched", () => {
    expect(transitionStyle({ type: "cut", durationFrames: 0 }, 0, PUNCH_IN)).toEqual({
      opacity: 1,
      scale: 1,
      translateX: 0,
    });
  });

  it("zooms a punch-in for the whole clip without any ramp", () => {
    const punchIn = { type: "punch_in", durationFrames: 0 } as const;
    expect([0, 40].map((frame) => transitionStyle(punchIn, frame, PUNCH_IN).scale)).toEqual([
      PUNCH_IN,
      PUNCH_IN,
    ]);
  });

  it("fades in from black over its duration", () => {
    const fade = { type: "fade", durationFrames: 10 } as const;
    expect([0, 5, 10, 20].map((frame) => transitionStyle(fade, frame, PUNCH_IN).opacity)).toEqual([
      0, 0.5, 1, 1,
    ]);
  });

  it("slides in from the right and settles at its duration", () => {
    const slide = { type: "slide", durationFrames: 8 } as const;
    const offsets = [0, 4, 8, 12].map(
      (frame) => transitionStyle(slide, frame, PUNCH_IN).translateX,
    );
    expect(offsets[0]).toBe(1);
    expect(offsets[1]).toBeGreaterThan(0);
    expect(offsets[1]).toBeLessThan(0.5);
    expect(offsets.slice(2)).toEqual([0, 0]);
  });

  it("treats a zero-length fade or slide as a cut", () => {
    expect(transitionStyle({ type: "fade", durationFrames: 0 }, 0, PUNCH_IN).opacity).toBe(1);
    expect(transitionStyle({ type: "slide", durationFrames: 0 }, 0, PUNCH_IN).translateX).toBe(0);
  });
});
