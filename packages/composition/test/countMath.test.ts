import { describe, expect, it } from "vitest";

import {
  countDecimals,
  countUpValue,
  formatCount,
  ringDashOffset,
  ringProgress,
} from "../src/overlays/countMath";

const FPS = 30;

describe("count_up", () => {
  it("counts from zero to the value over 1.2 s, fast first, and holds it", () => {
    expect(countUpValue(0, FPS, 1000)).toBe(0);
    // Ease-out expo: 87.5 % of the way after a quarter of the count (9 of 36 frames).
    expect(countUpValue(9, FPS, 1000)).toBeCloseTo(1000 * (1 - 2 ** -2.5), 6);
    expect(countUpValue(36, FPS, 1000)).toBe(1000);
    expect(countUpValue(90, FPS, 1000)).toBe(1000);
  });

  it("keeps up to two of the value's decimals and groups thousands with a no-break space", () => {
    expect(countDecimals(12)).toBe(0);
    expect(countDecimals(4.5)).toBe(1);
    expect(countDecimals(3.14159)).toBe(2);
    expect(formatCount(1234567, 0)).toBe("1\u00a0234\u00a0567");
    expect(formatCount(999.456, 1)).toBe("999.5");
    expect(formatCount(0, 2)).toBe("0.00");
  });
});

describe("progress_ring", () => {
  it("fills over the overlay's own span", () => {
    expect(ringProgress(0, 100)).toBe(0.01);
    expect(ringProgress(49, 100)).toBe(0.5);
    expect(ringProgress(99, 100)).toBe(1);
    expect(ringProgress(200, 100)).toBe(1);
  });

  it("turns progress into a stroke offset of the circle", () => {
    const circumference = 2 * Math.PI * 40;
    expect(ringDashOffset(0, 40)).toBeCloseTo(circumference, 6);
    expect(ringDashOffset(0.25, 40)).toBeCloseTo(circumference * 0.75, 6);
    expect(ringDashOffset(1, 40)).toBe(0);
  });
});
