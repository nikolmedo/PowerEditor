import type { Overlay } from "../types";

export interface OverlaySpan {
  overlay: Overlay;
  from: number;
  durationInFrames: number;
}

/**
 * Overlays as sequences of a `totalFrames` long timeline: each is clamped to the timeline and
 * one with nothing left to show is dropped (Remotion refuses empty sequences). Overlays never
 * lengthen the video; the duration comes from the clips alone.
 */
export function overlaySpans(overlays: readonly Overlay[], totalFrames: number): OverlaySpan[] {
  return overlays.flatMap((overlay) => {
    const from = Math.max(0, overlay.startFrame);
    const end = Math.min(totalFrames, overlay.endFrame);
    return end > from ? [{ overlay, from, durationInFrames: end - from }] : [];
  });
}
