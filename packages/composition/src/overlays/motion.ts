import { Easing, interpolate, spring } from "remotion";

/** Entrance length: a damped spring with no overshoot. */
export const ENTER_SECONDS = 0.4;
/** Exit length: an accelerating fall, shorter than the entrance. */
export const EXIT_SECONDS = 0.3;

/**
 * How present an overlay is at `frame` of its own span (0 hidden, 1 settled). An overlay
 * shorter than both animations splits its length between them.
 */
export function overlayMotion(frame: number, durationInFrames: number, fps: number): number {
  if (frame <= 0 || frame >= durationInFrames) return 0;
  const half = Math.floor(durationInFrames / 2);
  const enter = Math.max(1, Math.min(Math.round(ENTER_SECONDS * fps), half));
  const entering =
    frame >= enter ? 1 : spring({ frame, fps, durationInFrames: enter, config: { damping: 200 } });
  return Math.min(entering, overlayExit(frame, durationInFrames, fps));
}

/**
 * The exit alone (1 until the last 0.3 s, then an accelerating fall to 0), for looks that
 * choreograph their own entrance but leave like every other graphic.
 */
export function overlayExit(frame: number, durationInFrames: number, fps: number): number {
  if (frame >= durationInFrames) return 0;
  const half = Math.floor(durationInFrames / 2);
  const exit = Math.max(1, Math.min(Math.round(EXIT_SECONDS * fps), half));
  return interpolate(frame, [durationInFrames - exit, durationInFrames], [1, 0], {
    easing: Easing.in(Easing.cubic),
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
}
