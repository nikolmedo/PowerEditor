import { Easing, interpolate, spring } from "remotion";

/**
 * Entrance timing of the variant looks, in seconds. Ported as designs from the HyperFrames
 * registry (Apache-2.0); the values are our own and pinned by `test/variants.test.ts`.
 * Exits stay shared (`overlayExit`), so every graphic leaves the same way.
 */
export const VARIANT_TIMING = {
  /** A bar wipes in, then the text is unmasked behind it. */
  maskReveal: { barSeconds: 0.35, textDelay: 0.15, textSeconds: 0.4 },
  /** The kicker rises first, the name follows. */
  kickerName: { kickerSeconds: 0.3, nameDelay: 0.12, nameSeconds: 0.35 },
  /** The CTA arrow slides in after the text has landed. */
  lockup: { arrowDelay: 0.2, arrowSeconds: 0.3 },
  /** The closing card dims the frame while its line rises. */
  close: { scrimOpacity: 0.6, riseSeconds: 0.45 },
} as const;

/** Start and end scale of `headline_slam` and the spring that joins them (overshoots). */
const SLAM_FROM = 1.8;
const SLAM_SPRING = { damping: 10, mass: 0.6, stiffness: 180 };
const SLAM_FADE_FRAMES = 2;

/** 0 → 1 with an ease-out cubic over `seconds`, starting `delay` seconds into the overlay. */
export function revealProgress(frame: number, fps: number, delay: number, seconds: number): number {
  const start = delay * fps;
  return interpolate(frame, [start, start + seconds * fps], [0, 1], {
    easing: Easing.out(Easing.cubic),
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
}

/** Scale of a slammed headline: lands from 1.8x, dips under 1 once and settles at 1. */
export function slamScale(frame: number, fps: number): number {
  const settle = spring({ frame, fps, config: SLAM_SPRING });
  return SLAM_FROM - (SLAM_FROM - 1) * settle;
}

/** A slam is visible almost at once: two frames of fade so the first frame is not a pop. */
export function slamOpacity(frame: number): number {
  return interpolate(frame, [0, SLAM_FADE_FRAMES], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
}
