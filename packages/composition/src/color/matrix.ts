import type { ColorCorrection, ColorGrade, ColorGradeOverride } from "../types";

/**
 * Color grading as one SVG `feColorMatrix` (4x5, row-major, applied to sRGB values in 0..1).
 * The same matrix runs in the Player and in the render because both use this composition.
 *
 * A clip's matrix is: source correction (auto match), then brightness, contrast, saturation
 * and temperature of the global grade merged with the clip's override.
 */

export type Matrix = number[];
export type GradeValues = Pick<
  ColorGrade,
  "brightness" | "contrast" | "saturation" | "temperature"
>;

/** Rec. 709 luma weights, as in the backend's color stats. */
const LUMA = [0.2126, 0.7152, 0.0722] as const;
/** Red gain at temperature 1 (blue gets the opposite). */
const TEMPERATURE_STRENGTH = 0.2;

// prettier-ignore
export const IDENTITY: Matrix = [
  1, 0, 0, 0, 0,
  0, 1, 0, 0, 0,
  0, 0, 1, 0, 0,
  0, 0, 0, 1, 0,
];

export const PRESET_VALUES: Record<ColorGrade["preset"], GradeValues> = {
  natural: { brightness: 1, contrast: 1, saturation: 1, temperature: 0 },
  warm: { brightness: 1, contrast: 1, saturation: 1.1, temperature: 0.35 },
  cool: { brightness: 1, contrast: 1, saturation: 0.95, temperature: -0.35 },
  bw: { brightness: 1, contrast: 1.1, saturation: 0, temperature: 0 },
};

/** A matrix scaling RGB by `gains` and adding `offset` to each channel. */
function diagonal(gains: readonly [number, number, number], offset = 0): Matrix {
  const [r, g, b] = gains;
  // prettier-ignore
  return [
    r, 0, 0, 0, offset,
    0, g, 0, 0, offset,
    0, 0, b, 0, offset,
    0, 0, 0, 1, 0,
  ];
}

function saturationMatrix(s: number): Matrix {
  const row = (channel: number) => [
    ...LUMA.map((weight, index) => (1 - s) * weight + (index === channel ? s : 0)),
    0,
    0,
  ];
  return [...row(0), ...row(1), ...row(2), 0, 0, 0, 1, 0];
}

/** `outer` applied after `inner`. */
export function compose(outer: Matrix, inner: Matrix): Matrix {
  const at = (matrix: Matrix, row: number, col: number) => matrix[row * 5 + col] ?? 0;
  const result: Matrix = [];
  for (let row = 0; row < 4; row++) {
    for (let col = 0; col < 5; col++) {
      let value = col === 4 ? at(outer, row, 4) : 0;
      for (let k = 0; k < 4; k++) value += at(outer, row, k) * at(inner, k, col);
      result.push(value);
    }
  }
  return result;
}

export function gradeMatrix({
  brightness,
  contrast,
  saturation,
  temperature,
}: GradeValues): Matrix {
  const warmth = TEMPERATURE_STRENGTH * temperature;
  return [
    diagonal([1 + warmth, 1, 1 - warmth]),
    saturationMatrix(saturation),
    diagonal([contrast, contrast, contrast], 0.5 * (1 - contrast)),
    diagonal([brightness, brightness, brightness]),
  ].reduce(compose);
}

/** The global grade with the values a clip override sets. */
export function resolveGrade(
  grade: ColorGrade,
  override: ColorGradeOverride | null | undefined,
): ColorGrade {
  if (!override) return grade;
  const set = Object.entries(override).filter(([, value]) => value !== null && value !== undefined);
  return { ...grade, ...Object.fromEntries(set) };
}

const isIdentity = (matrix: Matrix) =>
  matrix.every((value, index) => Math.abs(value - (IDENTITY[index] ?? 0)) < 1e-9);

/** The full matrix of one clip, or null when it leaves the picture unchanged. */
export function clipColorMatrix(
  grade: ColorGrade,
  correction: ColorCorrection | null | undefined,
  override: ColorGradeOverride | null | undefined,
): Matrix | null {
  const gains = correction
    ? diagonal([correction.redGain, correction.greenGain, correction.blueGain])
    : IDENTITY;
  const matrix = compose(gradeMatrix(resolveGrade(grade, override)), gains);
  return isIdentity(matrix) ? null : matrix;
}
