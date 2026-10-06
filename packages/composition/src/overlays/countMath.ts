import { Easing, interpolate } from "remotion";

/** How long `count_up` takes to reach its value. */
export const COUNT_SECONDS = 1.2;
const MAX_DECIMALS = 2;
/** Groups thousands without a locale, so the Player and the render print the same text. */
const GROUP_SEPARATOR = "\u00a0";

/** The counter at `frame` of its overlay: an ease-out from 0 to `target`, then held. */
export function countUpValue(frame: number, fps: number, target: number): number {
  const end = COUNT_SECONDS * fps;
  // The exponential curve only nears 1; land exactly on the value.
  if (frame >= end) return target;
  return interpolate(frame, [0, end], [0, target], {
    easing: Easing.out(Easing.exp),
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
}

/** Decimals of `value` worth showing while counting: as many as it has, two at most. */
export function countDecimals(value: number): number {
  for (let decimals = 0; decimals < MAX_DECIMALS; decimals++) {
    const scaled = value * 10 ** decimals;
    if (Math.abs(scaled - Math.round(scaled)) < 1e-9) return decimals;
  }
  return MAX_DECIMALS;
}

/** `value` with `decimals` decimals, a point, and grouped thousands. */
export function formatCount(value: number, decimals: number): string {
  const [whole = "0", fraction] = value.toFixed(decimals).split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, GROUP_SEPARATOR);
  return fraction === undefined ? grouped : `${grouped}.${fraction}`;
}

/** Share of the ring filled at `frame` of a `durationInFrames` long overlay (full on its last). */
export function ringProgress(frame: number, durationInFrames: number): number {
  return Math.min(1, (frame + 1) / Math.max(1, durationInFrames));
}

/** `stroke-dashoffset` that shows `progress` of a circle of `radius`. */
export function ringDashOffset(progress: number, radius: number): number {
  return 2 * Math.PI * radius * (1 - progress);
}
