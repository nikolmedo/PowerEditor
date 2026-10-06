import { describe, expect, it } from "vitest";

import {
  clipColorMatrix,
  gradeMatrix,
  IDENTITY,
  PRESET_VALUES,
  resolveGrade,
} from "../src/color/matrix";
import type { ColorGrade } from "../src/types";

const grade = (preset: ColorGrade["preset"]): ColorGrade => ({ preset, ...PRESET_VALUES[preset] });
const expectMatrix = (actual: number[], expected: number[]) => {
  expect(actual).toHaveLength(20);
  actual.forEach((value, index) => expect(value).toBeCloseTo(expected[index] ?? NaN, 6));
};

describe("gradeMatrix", () => {
  it("is the identity for the natural preset", () => {
    expectMatrix(gradeMatrix(grade("natural")), IDENTITY);
  });

  it("turns every channel into Rec. 709 luma with a little contrast for black and white", () => {
    const row = [0.23386, 0.78672, 0.07942, 0, -0.05];
    expectMatrix(gradeMatrix(grade("bw")), [...row, ...row, ...row, 0, 0, 0, 1, 0]);
  });

  it("saturates and shifts red up and blue down for warm, the reverse for cool", () => {
    expectMatrix(
      gradeMatrix(grade("warm")),
      // prettier-ignore
      [
        1.1542518, -0.0765264, -0.0077254, 0, 0,
        -0.02126, 1.02848, -0.00722, 0, 0,
        -0.0197718, -0.0665136, 1.0162854, 0, 0,
        0, 0, 0, 1, 0,
      ],
    );
    const cool = gradeMatrix(grade("cool"));
    expect(cool[0]).toBeLessThan(1);
    expect(cool[12]).toBeGreaterThan(1);
  });

  it("scales for brightness and pivots contrast around mid grey", () => {
    const brighter = gradeMatrix({ ...grade("natural"), brightness: 1.2 });
    expect([brighter[0], brighter[6], brighter[12], brighter[4]]).toEqual([1.2, 1.2, 1.2, 0]);
    const flat = gradeMatrix({ ...grade("natural"), contrast: 0.5 });
    expect([flat[0], flat[4]]).toEqual([0.5, 0.25]);
  });
});

describe("resolveGrade", () => {
  it("lets a clip override replace only the values it sets", () => {
    const global = grade("warm");
    expect(resolveGrade(global, { brightness: 1.3 })).toEqual({ ...global, brightness: 1.3 });
    expect(resolveGrade(global, { brightness: null })).toEqual(global);
    expect(resolveGrade(global, undefined)).toEqual(global);
  });
});

describe("clipColorMatrix", () => {
  it("applies the source correction before the grade", () => {
    const matrix = clipColorMatrix(
      { ...grade("natural"), brightness: 0.5 },
      { redGain: 1.2, greenGain: 1, blueGain: 0.8 },
      null,
    );
    expect([matrix?.[0], matrix?.[6], matrix?.[12]]).toEqual([0.6, 0.5, 0.4]);
  });

  it("is null when nothing changes the picture", () => {
    expect(clipColorMatrix(grade("natural"), null, null)).toBeNull();
    expect(clipColorMatrix(grade("natural"), null, { saturation: 1 })).toBeNull();
  });
});
