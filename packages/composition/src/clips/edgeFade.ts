import { roundHalfEven } from "../timeline";

/**
 * Length of the per-clip edge fade that smooths each cut.
 *
 * Volume is evaluated once per frame, so a crossfade shorter than one frame
 * (15 ms at 30 fps) is stretched to a single frame rather than dropped.
 */
export function edgeFadeFrames(ms: number, fps: number): number {
  if (ms <= 0) return 0;
  return Math.max(1, roundHalfEven((ms * fps) / 1000));
}

/** Gain for `frame` of a clip: linear fade-in and fade-out sampled at frame centres. */
export function edgeFadeGain(frame: number, durationInFrames: number, fadeFrames: number): number {
  const fade = Math.min(fadeFrames, Math.floor(durationInFrames / 2));
  if (fade <= 0) return 1;
  const fadeIn = (frame + 0.5) / fade;
  const fadeOut = (durationInFrames - frame - 0.5) / fade;
  return Math.max(0, Math.min(1, fadeIn, fadeOut));
}
